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

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.success / self.total * 100

    @property
    def failed_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.failed / self.total * 100

    @property
    def actual_sent(self) -> int:
        return self.success + self.failed

    @property
    def failure_reasons(self) -> Dict[str, int]:
        reasons: Dict[str, int] = {}
        for r in self.results:
            if r.status == SendStatus.FAILED:
                reason = r.message or "未知错误"
                reasons[reason] = reasons.get(reason, 0) + 1
        return dict(sorted(reasons.items(), key=lambda x: -x[1]))

    def get_by_status(self, status: SendStatus) -> List[SendResult]:
        return [r for r in self.results if r.status == status]

    def get_failed_phones(self) -> List[str]:
        return [r.phone for r in self.results if r.status == SendStatus.FAILED]

    def get_success_phones(self) -> List[str]:
        return [r.phone for r in self.results if r.status == SendStatus.SUCCESS]

    def get_blacklisted_phones(self) -> List[str]:
        return [r.phone for r in self.results if r.status == SendStatus.BLACKLISTED]

    def get_invalid_phones(self) -> List[str]:
        return [r.phone for r in self.results if r.status == SendStatus.INVALID]

    def summary(self) -> str:
        return (
            f"发送报告: 总计={self.total}, 成功={self.success}, "
            f"失败={self.failed}, 黑名单={self.blacklisted}, "
            f"无效号码={self.invalid}, 耗时={self.duration:.2f}s"
        )

    def detailed_report(self) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("短信批量发送报告")
        lines.append("=" * 60)
        lines.append(f"总计号码数:       {self.total}")
        lines.append(f"成功发送数:       {self.success}  ({self.success_rate:.2f}%)")
        lines.append(f"发送失败数:       {self.failed}  ({self.failed_rate:.2f}%)")
        lines.append(f"黑名单过滤数:     {self.blacklisted}")
        lines.append(f"无效号码数:       {self.invalid}")
        lines.append(f"实际发送量:       {self.actual_sent}")
        lines.append(f"总耗时:           {self.duration:.2f} 秒")
        if self.actual_sent > 0 and self.duration > 0:
            lines.append(f"平均速率:         {self.actual_sent / self.duration:.2f} 条/秒")
        lines.append("-" * 60)

        if self.failure_reasons:
            lines.append("失败原因统计:")
            for reason, count in self.failure_reasons.items():
                pct = count / self.failed * 100 if self.failed > 0 else 0
                lines.append(f"  [{count:3d}] {reason}  ({pct:.1f}%)")
            lines.append("-" * 60)

        if self.success > 0:
            lines.append(f"成功号码 ({self.success} 个):")
            for r in self.get_by_status(SendStatus.SUCCESS):
                lines.append(f"  ✅ {r.phone}")
            lines.append("-" * 60)

        if self.failed > 0:
            lines.append(f"失败号码 ({self.failed} 个):")
            for r in self.get_by_status(SendStatus.FAILED):
                lines.append(f"  ❌ {r.phone} - {r.message}")
            lines.append("-" * 60)

        if self.blacklisted > 0:
            lines.append(f"黑名单号码 ({self.blacklisted} 个):")
            for phone in self.get_blacklisted_phones():
                lines.append(f"  ⛔ {phone}")
            lines.append("-" * 60)

        if self.invalid > 0:
            lines.append(f"无效号码 ({self.invalid} 个):")
            for phone in self.get_invalid_phones():
                lines.append(f"  ⚠️  {phone}")
            lines.append("-" * 60)

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "blacklisted": self.blacklisted,
            "invalid": self.invalid,
            "duration": round(self.duration, 2),
            "success_rate": round(self.success_rate, 2),
            "failed_rate": round(self.failed_rate, 2),
            "actual_sent": self.actual_sent,
            "failure_reasons": self.failure_reasons,
            "results": [
                {
                    "phone": r.phone,
                    "status": r.status.value,
                    "message": r.message,
                    "timestamp": r.timestamp,
                }
                for r in self.results
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def export_to_file(self, filepath: str) -> None:
        path = Path(filepath)
        suffix = path.suffix.lower()
        if suffix == ".json":
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.to_json())
        elif suffix == ".csv":
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["手机号", "状态", "消息", "时间戳"])
                for r in self.results:
                    writer.writerow([
                        r.phone,
                        r.status.value,
                        r.message,
                        r.timestamp,
                    ])
        elif suffix in (".txt", ".log", ""):
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.detailed_report())
        else:
            logger.warning(f"不支持的报告格式 {suffix}，默认使用 TXT 格式")
            with open(path.with_suffix(".txt"), "w", encoding="utf-8") as f:
                f.write(self.detailed_report())
        logger.info(f"发送报告已导出到: {filepath}")


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


async def _flaky_sender(phone: str, content: str) -> bool:
    import random
    await asyncio.sleep(0.01)
    roll = random.random()
    if roll < 0.15:
        raise ConnectionError("短信网关连接超时")
    elif roll < 0.25:
        raise ValueError("签名校验失败")
    elif roll < 0.35:
        raise RuntimeError("账户余额不足")
    elif roll < 0.45:
        return False
    logger.info(f"[模拟发送] -> {phone}: {content}")
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
    print()
    print("=" * 70)
    print("演示 1: 基础批量发送 + 汇总报告")
    print("=" * 70)
    service = SmsService(rate_per_second=100.0)
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
    print()
    print(report.summary())
    print()

    print("=" * 70)
    print("演示 2: 详细报告（含成功率、速率、各类号码清单）")
    print("=" * 70)
    print(report.detailed_report())

    print()
    print("=" * 70)
    print("演示 3: 发送失败 + 失败原因统计 + 多格式报告导出")
    print("=" * 70)
    import random
    random.seed(42)
    service2 = SmsService(rate_per_second=100.0, sender=_flaky_sender)
    service2.blacklist.add("13800000011")

    phones2 = [
        "13800000011",
        "123456",
        "13910000001",
        "13910000002",
        "13910000003",
        "13910000004",
        "13910000005",
        "13910000006",
        "13910000007",
        "13910000008",
        "13910000009",
        "13910000010",
        "13910000011",
        "13910000012",
        "13910000013",
        "13910000014",
        "13910000015",
        "13910000016",
        "13910000017",
        "13910000018",
        "13910000019",
        "13910000020",
    ]

    report2 = await service2.send_batch(phones2, content)
    print(report2.detailed_report())

    print()
    print("失败原因统计 (failure_reasons):")
    if report2.failure_reasons:
        for reason, count in report2.failure_reasons.items():
            print(f"  {count:3d} 次 - {reason}")
    else:
        print("  (无失败)")

    print()
    print("导出报告到文件...")
    report2.export_to_file("report.txt")
    report2.export_to_file("report.csv")
    report2.export_to_file("report.json")
    print("已生成: report.txt, report.csv, report.json")

    print()
    print("=" * 70)
    print("演示 4: 数据接口调用示例")
    print("=" * 70)
    print(f"成功率:        {report2.success_rate:.2f}%")
    print(f"失败率:        {report2.failed_rate:.2f}%")
    print(f"实际发送量:    {report2.actual_sent}")
    print(f"成功号码数:    {len(report2.get_success_phones())}")
    print(f"失败号码数:    {len(report2.get_failed_phones())}")
    print(f"黑名单号码数:  {len(report2.get_blacklisted_phones())}")
    print(f"无效号码数:    {len(report2.get_invalid_phones())}")
    data = report2.to_dict()
    print(f"to_dict() keys: {list(data.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
