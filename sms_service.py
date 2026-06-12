import asyncio
import time
import re
import csv
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Set, Optional, Callable, Awaitable, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


class SendStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    BLACKLISTED = "blacklisted"
    INVALID = "invalid"


@dataclass
class SendResult:
    phone: str
    status: SendStatus
    message: str = ""
    timestamp: float = 0.0


@dataclass
class BatchReport:
    total: int = 0
    success: int = 0
    failed: int = 0
    blacklisted: int = 0
    invalid: int = 0
    duration: float = 0.0
    results: List[SendResult] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"发送报告: 总计={self.total}, 成功={self.success}, "
            f"失败={self.failed}, 黑名单={self.blacklisted}, "
            f"无效号码={self.invalid}, 耗时={self.duration:.2f}s"
        )


class RateLimiter:
    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = rate
        self._max_tokens = rate
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            while self._tokens < 1.0:
                self._refill()
                if self._tokens < 1.0:
                    deficit = 1.0 - self._tokens
                    wait = deficit / self._rate
                    await asyncio.sleep(wait)
                    self._refill()
            self._tokens -= 1.0

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._rate)
        self._last_refill = now


class PhoneValidator:
    _FULLWIDTH_DIGITS = str.maketrans(
        "０１２３４５６７８９",
        "0123456789"
    )
    _FULLWIDTH_CHARS = str.maketrans({
        "　": " ",
        "－": "-",
        "（": "(",
        "）": ")",
        "＋": "+",
    })

    @staticmethod
    def normalize(phone: str) -> str:
        if not isinstance(phone, str):
            return ""
        cleaned = phone.translate(PhoneValidator._FULLWIDTH_CHARS)
        cleaned = cleaned.translate(PhoneValidator._FULLWIDTH_DIGITS)
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("0086") and len(digits) == 15:
            digits = digits[4:]
        elif digits.startswith("86") and len(digits) == 13:
            digits = digits[2:]
        return digits

    @staticmethod
    def validate(phone: str) -> bool:
        normalized = PhoneValidator.normalize(phone)
        return bool(PHONE_PATTERN.match(normalized))


class BlacklistManager:
    def __init__(self):
        self._blacklist: Set[str] = set()

    def add(self, phone: str) -> None:
        normalized = PhoneValidator.normalize(phone)
        self._blacklist.add(normalized)

    def add_many(self, phones: List[str]) -> int:
        count = 0
        for phone in phones:
            normalized = PhoneValidator.normalize(phone)
            if normalized not in self._blacklist:
                self._blacklist.add(normalized)
                count += 1
        return count

    def remove(self, phone: str) -> bool:
        normalized = PhoneValidator.normalize(phone)
        if normalized in self._blacklist:
            self._blacklist.discard(normalized)
            return True
        return False

    def is_blacklisted(self, phone: str) -> bool:
        return PhoneValidator.normalize(phone) in self._blacklist

    def filter_blacklisted(self, phones: List[str]) -> tuple:
        valid = []
        blacklisted = []
        for phone in phones:
            normalized = PhoneValidator.normalize(phone)
            if normalized in self._blacklist:
                blacklisted.append(normalized)
            else:
                valid.append(normalized)
        return valid, blacklisted

    def load_from_file(self, filepath: str) -> int:
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"黑名单文件不存在: {filepath}")
            return 0

        phones = []
        if path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                phones = data if isinstance(data, list) else data.get("blacklist", [])
        elif path.suffix in (".csv", ".txt"):
            with open(path, "r", encoding="utf-8") as f:
                if path.suffix == ".csv":
                    reader = csv.reader(f)
                    for row in reader:
                        phones.extend(row)
                else:
                    phones = [line.strip() for line in f if line.strip()]
        else:
            logger.error(f"不支持的黑名单文件格式: {path.suffix}")
            return 0

        return self.add_many(phones)

    def save_to_file(self, filepath: str) -> None:
        path = Path(filepath)
        with open(path, "w", encoding="utf-8") as f:
            if path.suffix == ".json":
                json.dump(sorted(self._blacklist), f, ensure_ascii=False, indent=2)
            elif path.suffix == ".csv":
                writer = csv.writer(f)
                for phone in sorted(self._blacklist):
                    writer.writerow([phone])
            else:
                for phone in sorted(self._blacklist):
                    f.write(phone + "\n")

    @property
    def size(self) -> int:
        return len(self._blacklist)

    def clear(self) -> None:
        self._blacklist.clear()


class PhoneImporter:
    @staticmethod
    def from_list(phones: List[str]) -> List[str]:
        return [PhoneValidator.normalize(p) for p in phones]

    @staticmethod
    def from_file(filepath: str) -> List[str]:
        path = Path(filepath)
        if not path.exists():
            logger.error(f"手机号文件不存在: {filepath}")
            return []

        phones = []
        if path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                phones = data if isinstance(data, list) else data.get("phones", [])
        elif path.suffix == ".csv":
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    phones.extend(row)
        elif path.suffix in (".txt",):
            with open(path, "r", encoding="utf-8") as f:
                phones = [line.strip() for line in f if line.strip()]
        else:
            logger.error(f"不支持的文件格式: {path.suffix}")
            return []

        return [PhoneValidator.normalize(p) for p in phones]


SmsSender = Callable[[str, str], Awaitable[bool]]


async def _default_sender(phone: str, content: str) -> bool:
    logger.info(f"[模拟发送] -> {phone}: {content}")
    await asyncio.sleep(0.01)
    return True


class SmsService:
    def __init__(
        self,
        rate_per_second: float = 10.0,
        sender: Optional[SmsSender] = None,
    ):
        self._rate_limiter = RateLimiter(rate_per_second)
        self._blacklist_mgr = BlacklistManager()
        self._sender = sender or _default_sender
        self._rate = rate_per_second
        self._sent_count = 0

    @property
    def blacklist(self) -> BlacklistManager:
        return self._blacklist_mgr

    @property
    def rate(self) -> float:
        return self._rate

    @rate.setter
    def rate(self, value: float) -> None:
        self._rate = value
        self._rate_limiter = RateLimiter(value)

    @property
    def sent_count(self) -> int:
        return self._sent_count

    def import_phones(self, phones: List[str]) -> List[str]:
        return PhoneImporter.from_list(phones)

    def import_phones_from_file(self, filepath: str) -> List[str]:
        return PhoneImporter.from_file(filepath)

    def _filter_and_validate(self, phones: List[str]) -> tuple:
        valid_phones = []
        results: List[SendResult] = []

        for phone in phones:
            normalized = PhoneValidator.normalize(phone)
            if not PhoneValidator.validate(normalized):
                results.append(SendResult(
                    phone=normalized,
                    status=SendStatus.INVALID,
                    message="无效的手机号码",
                ))
                continue
            if self._blacklist_mgr.is_blacklisted(normalized):
                results.append(SendResult(
                    phone=normalized,
                    status=SendStatus.BLACKLISTED,
                    message="号码在黑名单中",
                ))
                continue
            valid_phones.append(normalized)

        return valid_phones, results

    async def send_one(self, phone: str, content: str) -> SendResult:
        normalized = PhoneValidator.normalize(phone)
        if not PhoneValidator.validate(normalized):
            return SendResult(phone=normalized, status=SendStatus.INVALID, message="无效的手机号码")

        if self._blacklist_mgr.is_blacklisted(normalized):
            return SendResult(phone=normalized, status=SendStatus.BLACKLISTED, message="号码在黑名单中")

        await self._rate_limiter.acquire()
        try:
            success = await self._sender(normalized, content)
            self._sent_count += 1
            return SendResult(
                phone=normalized,
                status=SendStatus.SUCCESS if success else SendStatus.FAILED,
                message="" if success else "发送失败",
                timestamp=time.time(),
            )
        except Exception as e:
            return SendResult(
                phone=normalized,
                status=SendStatus.FAILED,
                message=str(e),
                timestamp=time.time(),
            )

    async def send_batch(
        self,
        phones: List[str],
        content: str,
        on_progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
    ) -> BatchReport:
        start_time = time.monotonic()
        report = BatchReport(total=len(phones))

        valid_phones, pre_results = self._filter_and_validate(phones)
        report.results.extend(pre_results)

        for r in pre_results:
            if r.status == SendStatus.BLACKLISTED:
                report.blacklisted += 1
            elif r.status == SendStatus.INVALID:
                report.invalid += 1

        tasks = []
        for phone in valid_phones:
            tasks.append(self._send_single(phone, content))

        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            report.results.append(result)
            if result.status == SendStatus.SUCCESS:
                report.success += 1
            else:
                report.failed += 1
            completed += 1
            if on_progress:
                await on_progress(completed + len(pre_results), report.total)

        report.duration = time.monotonic() - start_time
        return report

    async def _send_single(self, phone: str, content: str) -> SendResult:
        await self._rate_limiter.acquire()
        try:
            success = await self._sender(phone, content)
            self._sent_count += 1
            return SendResult(
                phone=phone,
                status=SendStatus.SUCCESS if success else SendStatus.FAILED,
                message="" if success else "发送失败",
                timestamp=time.time(),
            )
        except Exception as e:
            return SendResult(
                phone=phone,
                status=SendStatus.FAILED,
                message=str(e),
                timestamp=time.time(),
            )


async def progress_callback(current: int, total: int) -> None:
    logger.info(f"发送进度: {current}/{total} ({current/total*100:.1f}%)")


async def main():
    service = SmsService(rate_per_second=5.0)
    logger.info(f"短信服务已启动，发送频率: {service.rate} 条/秒")

    service.blacklist.add("13800000001")
    service.blacklist.add("13800000002")
    logger.info(f"黑名单加载完成，共 {service.blacklist.size} 个号码")

    phones = [
        "13800000001",
        "13900000002",
        "13700000003",
        "13600000004",
        "13500000005",
        "13400000006",
        "12345678901",
        "13800000002",
        "13300000009",
        "13200000010",
    ]

    content = "【测试短信】您的验证码是 123456，请在5分钟内使用。"

    logger.info(f"开始批量发送短信，目标号码数: {len(phones)}")
    report = await service.send_batch(phones, content, on_progress=progress_callback)

    logger.info("=" * 60)
    logger.info(report.summary())
    logger.info("=" * 60)

    for result in report.results:
        logger.info(f"[{result.status.value}] {result.phone} - {result.message}")


if __name__ == "__main__":
    asyncio.run(main())
