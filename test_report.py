import asyncio
import json
import csv
import sys
import os
sys.path.insert(0, '.')
from sms_service import (
    SmsService, BatchReport, SendResult, SendStatus,
    PhoneValidator, BlacklistManager
)


async def deterministic_failure_sender(phone: str, content: str):
    mapping = {
        "13910000001": (True, None),
        "13910000002": (True, None),
        "13910000003": (True, None),
        "13910000004": (True, None),
        "13910000005": (False, None),
        "13910000006": (None, ConnectionError("短信网关连接超时")),
        "13910000007": (None, ConnectionError("短信网关连接超时")),
        "13910000008": (None, ValueError("签名校验失败")),
        "13910000009": (None, RuntimeError("账户余额不足")),
    }
    import asyncio as _aio
    await _aio.sleep(0.001)
    ok, exc = mapping.get(phone, (True, None))
    if exc is not None:
        raise exc
    return ok


def test_report_basic_stats():
    print("=" * 60)
    print("测试 1: BatchReport 基础统计")
    print("=" * 60)

    report = BatchReport(total=10)
    report.success = 6
    report.failed = 2
    report.blacklisted = 1
    report.invalid = 1
    report.duration = 3.5

    assert report.total == 10
    assert report.success == 6
    assert report.failed == 2
    assert report.blacklisted == 1
    assert report.invalid == 1
    assert report.actual_sent == 8
    assert abs(report.success_rate - 60.0) < 0.01
    assert abs(report.failed_rate - 20.0) < 0.01

    print("  ✅ total/success/failed/blacklisted/invalid 字段正确")
    print("  ✅ actual_sent = success + failed")
    print("  ✅ success_rate / failed_rate 百分比计算正确")


def test_report_failure_reasons():
    print("\n" + "=" * 60)
    print("测试 2: 失败原因统计 failure_reasons")
    print("=" * 60)

    report = BatchReport()
    report.results = [
        SendResult("13910000006", SendStatus.FAILED, "短信网关连接超时"),
        SendResult("13910000007", SendStatus.FAILED, "短信网关连接超时"),
        SendResult("13910000008", SendStatus.FAILED, "签名校验失败"),
        SendResult("13910000009", SendStatus.FAILED, "账户余额不足"),
        SendResult("13910000005", SendStatus.FAILED, "发送失败"),
        SendResult("13910000010", SendStatus.FAILED, ""),
        SendResult("13910000001", SendStatus.SUCCESS, ""),
        SendResult("13910000002", SendStatus.SUCCESS, ""),
        SendResult("13800000001", SendStatus.BLACKLISTED, "号码在黑名单中"),
        SendResult("12345", SendStatus.INVALID, "无效的手机号码"),
    ]
    report.success = 2
    report.failed = 6
    report.blacklisted = 1
    report.invalid = 1
    report.total = 10

    reasons = report.failure_reasons
    print(f"  failure_reasons = {reasons}")

    assert reasons["短信网关连接超时"] == 2
    assert reasons["签名校验失败"] == 1
    assert reasons["账户余额不足"] == 1
    assert reasons["发送失败"] == 1
    assert reasons["未知错误"] == 1
    assert len(reasons) == 5

    first_key = list(reasons.keys())[0]
    assert reasons[first_key] == max(reasons.values()), "失败原因应按次数降序排列"

    print("  ✅ 失败原因分组统计正确（含空消息→'未知错误'）")
    print("  ✅ 失败原因按次数降序排列")
    print("  ✅ 只统计 FAILED 状态，忽略 SUCCESS/BLACKLISTED/INVALID")


def test_report_get_by_status_and_lists():
    print("\n" + "=" * 60)
    print("测试 3: get_by_status / get_*_phones 方法")
    print("=" * 60)

    report = BatchReport()
    report.results = [
        SendResult("13910000001", SendStatus.SUCCESS, ""),
        SendResult("13910000002", SendStatus.SUCCESS, ""),
        SendResult("13910000003", SendStatus.FAILED, "超时"),
        SendResult("13800000001", SendStatus.BLACKLISTED, "黑名单"),
        SendResult("13800000002", SendStatus.BLACKLISTED, "黑名单"),
        SendResult("abc", SendStatus.INVALID, "无效"),
    ]

    assert len(report.get_by_status(SendStatus.SUCCESS)) == 2
    assert len(report.get_by_status(SendStatus.FAILED)) == 1
    assert len(report.get_by_status(SendStatus.BLACKLISTED)) == 2
    assert len(report.get_by_status(SendStatus.INVALID)) == 1

    success_phones = report.get_success_phones()
    failed_phones = report.get_failed_phones()
    black_phones = report.get_blacklisted_phones()
    invalid_phones = report.get_invalid_phones()

    assert success_phones == ["13910000001", "13910000002"]
    assert failed_phones == ["13910000003"]
    assert black_phones == ["13800000001", "13800000002"]
    assert invalid_phones == ["abc"]

    print("  ✅ get_by_status() 按状态筛选正确")
    print("  ✅ get_success_phones() / get_failed_phones() 正确")
    print("  ✅ get_blacklisted_phones() / get_invalid_phones() 正确")


def test_report_summary_and_detailed_report():
    print("\n" + "=" * 60)
    print("测试 4: summary() 与 detailed_report() 文本输出")
    print("=" * 60)

    report = BatchReport(total=5, success=3, failed=1,
                         blacklisted=1, invalid=0, duration=2.0)
    report.results = [
        SendResult("13910000001", SendStatus.SUCCESS, "", 1000.0),
        SendResult("13910000002", SendStatus.SUCCESS, "", 1001.0),
        SendResult("13910000003", SendStatus.SUCCESS, "", 1002.0),
        SendResult("13910000004", SendStatus.FAILED, "网关超时", 1003.0),
        SendResult("13800000001", SendStatus.BLACKLISTED, "号码在黑名单中"),
    ]

    summary = report.summary()
    print(f"  summary() = {summary}")
    assert "总计=5" in summary
    assert "成功=3" in summary
    assert "失败=1" in summary
    assert "黑名单=1" in summary

    detailed = report.detailed_report()
    print(f"  detailed_report() 长度: {len(detailed)} 字符")
    assert "短信批量发送报告" in detailed
    assert f"成功发送数" in detailed
    assert "失败原因统计" in detailed
    assert "成功号码" in detailed
    assert "失败号码" in detailed
    assert "黑名单号码" in detailed
    assert "网关超时" in detailed

    print("  ✅ summary() 汇总文本格式正确")
    print("  ✅ detailed_report() 包含各板块、成功率、失败原因等")


def test_report_to_dict_and_json():
    print("\n" + "=" * 60)
    print("测试 5: to_dict() 与 to_json() 序列化")
    print("=" * 60)

    report = BatchReport(total=3, success=2, failed=1, duration=1.5)
    report.results = [
        SendResult("13910000001", SendStatus.SUCCESS, "", 1000.0),
        SendResult("13910000002", SendStatus.SUCCESS, "", 1001.0),
        SendResult("13910000003", SendStatus.FAILED, "超时", 1002.0),
    ]

    data = report.to_dict()
    print(f"  to_dict() keys = {list(data.keys())}")

    assert data["total"] == 3
    assert data["success"] == 2
    assert data["failed"] == 1
    assert data["duration"] == 1.5
    assert abs(data["success_rate"] - 66.67) < 0.01
    assert data["actual_sent"] == 3
    assert len(data["results"]) == 3
    assert data["results"][0]["status"] == "success"
    assert data["results"][2]["message"] == "超时"

    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed == data
    print("  ✅ to_dict() 字段完整，数值正确")
    print("  ✅ to_json() 生成合法 JSON 且与 dict 一致")


def test_report_export_files(tmp_dir="report_test_output"):
    print("\n" + "=" * 60)
    print("测试 6: export_to_file() 多格式导出")
    print("=" * 60)

    os.makedirs(tmp_dir, exist_ok=True)
    report = BatchReport(total=3, success=2, failed=1, duration=1.0)
    report.results = [
        SendResult("13910000001", SendStatus.SUCCESS, "", 1000.0),
        SendResult("13910000002", SendStatus.SUCCESS, "", 1001.0),
        SendResult("13910000003", SendStatus.FAILED, "网关超时", 1002.0),
    ]

    txt_path = os.path.join(tmp_dir, "rep.txt")
    csv_path = os.path.join(tmp_dir, "rep.csv")
    json_path = os.path.join(tmp_dir, "rep.json")

    report.export_to_file(txt_path)
    report.export_to_file(csv_path)
    report.export_to_file(json_path)

    assert os.path.exists(txt_path)
    assert os.path.exists(csv_path)
    assert os.path.exists(json_path)

    with open(txt_path, "r", encoding="utf-8") as f:
        txt_content = f.read()
    assert "短信批量发送报告" in txt_content

    with open(json_path, "r", encoding="utf-8") as f:
        json_content = json.load(f)
    assert json_content["total"] == 3

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
    assert reader[0] == ["手机号", "状态", "消息", "时间戳"]
    assert reader[1][0] == "13910000001"
    assert len(reader) == 4

    # 清理
    for p in (txt_path, csv_path, json_path):
        os.remove(p)
    os.rmdir(tmp_dir)

    print("  ✅ TXT 导出成功，含详细报告")
    print("  ✅ JSON 导出成功，数据正确")
    print("  ✅ CSV 导出成功，带 BOM，表头/数据正确")


async def test_send_batch_integrated_report():
    print("\n" + "=" * 60)
    print("测试 7: send_batch() 集成测试（报告字段自动填充）")
    print("=" * 60)

    service = SmsService(rate_per_second=1000.0, sender=deterministic_failure_sender)
    service.blacklist.add("13800000011")

    phones = [
        "13800000011",
        "invalid-num",
        "13910000001",
        "13910000002",
        "13910000003",
        "13910000004",
        "13910000005",
        "13910000006",
        "13910000007",
        "13910000008",
        "13910000009",
    ]

    report = await service.send_batch(phones, "【测试】验证码 888888")

    print(f"  total = {report.total} (期望 11)")
    print(f"  success = {report.success} (期望 4)")
    print(f"  failed = {report.failed} (期望 5)")
    print(f"  blacklisted = {report.blacklisted} (期望 1)")
    print(f"  invalid = {report.invalid} (期望 1)")
    print(f"  duration > 0 = {report.duration > 0}")
    print(f"  results len = {len(report.results)} (期望 11)")

    assert report.total == 11
    assert report.success == 4
    assert report.failed == 5
    assert report.blacklisted == 1
    assert report.invalid == 1
    assert report.duration > 0
    assert len(report.results) == 11

    reasons = report.failure_reasons
    print(f"  failure_reasons = {reasons}")
    assert reasons.get("短信网关连接超时") == 2
    assert reasons.get("签名校验失败") == 1
    assert reasons.get("账户余额不足") == 1
    assert reasons.get("发送失败") == 1
    assert len(reasons) == 4

    assert len(report.get_success_phones()) == 4
    assert len(report.get_failed_phones()) == 5
    assert len(report.get_blacklisted_phones()) == 1
    assert len(report.get_invalid_phones()) == 1

    print("  ✅ send_batch 自动统计 total/success/failed/blacklisted/invalid")
    print("  ✅ duration 正确记录执行耗时")
    print("  ✅ failure_reasons 正确聚合各种异常与返回 False 的场景")
    print("  ✅ get_*_phones / get_by_status 返回正确")


async def main():
    all_passed = True
    tests = []

    try:
        test_report_basic_stats()
        tests.append(("基础统计字段", True))
    except Exception as e:
        tests.append(("基础统计字段", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    try:
        test_report_failure_reasons()
        tests.append(("失败原因统计", True))
    except Exception as e:
        tests.append(("失败原因统计", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    try:
        test_report_get_by_status_and_lists()
        tests.append(("状态筛选与号码列表", True))
    except Exception as e:
        tests.append(("状态筛选与号码列表", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    try:
        test_report_summary_and_detailed_report()
        tests.append(("文本报告输出", True))
    except Exception as e:
        tests.append(("文本报告输出", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    try:
        test_report_to_dict_and_json()
        tests.append(("序列化 to_dict / to_json", True))
    except Exception as e:
        tests.append(("序列化 to_dict / to_json", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    try:
        test_report_export_files()
        tests.append(("文件多格式导出", True))
    except Exception as e:
        tests.append(("文件多格式导出", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    try:
        await test_send_batch_integrated_report()
        tests.append(("send_batch 集成报告", True))
    except Exception as e:
        tests.append(("send_batch 集成报告", False))
        print(f"  ❌ 异常: {e}")
        all_passed = False

    print("\n" + "=" * 60)
    print("报告功能测试汇总")
    print("=" * 60)
    for name, ok in tests:
        print(f"  {'✅' if ok else '❌'} {name}")

    print("\n" + ("全部通过!" if all_passed else "存在失败!"))
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
