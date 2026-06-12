import asyncio
import sys
sys.path.insert(0, '.')
from sms_service import SmsService, progress_callback


async def test_file_import():
    service = SmsService(rate_per_second=10.0)

    loaded = service.blacklist.load_from_file("blacklist.json")
    print(f"从 JSON 加载黑名单: {loaded} 个号码")
    print(f"当前黑名单总数: {service.blacklist.size}")

    phones = service.import_phones_from_file("phones.txt")
    print(f"从 TXT 导入手机号: {len(phones)} 个")
    print(f"导入的号码: {phones}")

    content = "【测试短信】您的验证码是 654321，请在5分钟内使用。"

    print("\n开始批量发送...")
    report = await service.send_batch(phones, content, on_progress=progress_callback)

    print("\n" + "=" * 60)
    print(report.summary())
    print("=" * 60)

    for result in report.results:
        print(f"[{result.status.value}] {result.phone} - {result.message}")

    service.blacklist.save_to_file("blacklist_output.txt")
    print(f"\n黑名单已导出到 blacklist_output.txt")


if __name__ == "__main__":
    asyncio.run(test_file_import())
