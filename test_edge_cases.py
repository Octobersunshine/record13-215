import asyncio
import sys
sys.path.insert(0, '.')
from sms_service import SmsService, PhoneValidator, BlacklistManager, SendStatus


def test_phone_normalize():
    print("=" * 60)
    print("测试手机号归一化 normalize()")
    print("=" * 60)

    test_cases = [
        ("13800000001", "13800000001", "标准11位半角"),
        ("１３８０００００００１", "13800000001", "全角数字"),
        ("+86 138-0000-0001", "13800000001", "+86前缀+横杠空格"),
        ("008613800000001", "13800000001", "0086前缀"),
        ("8613800000001", "13800000001", "86前缀"),
        ("１３８－００００－０００１", "13800000001", "全角数字+全角横杠"),
        ("（＋８６）１３８　００００　０００１", "13800000001", "全角括号全角空格"),
        ("  138 0000 0001  ", "13800000001", "首尾空格"),
        ("138-0000-0001", "13800000001", "半角横杠分隔"),
        ("138.0000.0001", "13800000001", "点号分隔"),
        ("Abc138xyz0000test0001", "13800000001", "混入字母（大小写）"),
        ("ABC138XYZ0000TEST0001", "13800000001", "混入大写字母"),
        ("", "", "空字符串"),
        ("abc", "", "纯字母"),
        (None, "", "None输入"),
    ]

    all_passed = True
    for input_val, expected, desc in test_cases:
        result = PhoneValidator.normalize(input_val)
        passed = result == expected
        all_passed = all_passed and passed
        status = "✅" if passed else "❌"
        print(f"{status} [{desc}]")
        print(f"   输入: {repr(input_val)}")
        print(f"   期望: {expected}")
        print(f"   实际: {result}")
        if not passed:
            print("   【失败】")

    return all_passed


def test_phone_validate():
    print("\n" + "=" * 60)
    print("测试手机号验证 validate()")
    print("=" * 60)

    test_cases = [
        ("13800000001", True, "标准有效手机号"),
        ("１３８０００００００１", True, "全角有效手机号"),
        ("+8613800000001", True, "+86前缀有效"),
        ("008613800000001", True, "0086前缀有效"),
        ("12345678901", False, "1开头但第二位不对"),
        ("10800000001", False, "第二位0无效"),
        ("1380000000", False, "只有10位"),
        ("138000000012", False, "12位无正确前缀"),
        ("", False, "空字符串"),
        ("abcdefghijk", False, "纯字母"),
    ]

    all_passed = True
    for input_val, expected, desc in test_cases:
        result = PhoneValidator.validate(input_val)
        passed = result == expected
        all_passed = all_passed and passed
        status = "✅" if passed else "❌"
        print(f"{status} [{desc}] {input_val!r} -> {result} (期望: {expected})")

    return all_passed


def test_blacklist_filtering():
    print("\n" + "=" * 60)
    print("测试黑名单过滤（大小写/全角/各种格式）")
    print("=" * 60)

    bm = BlacklistManager()
    bm.add("13800000001")
    bm.add("13800000002")
    print(f"黑名单加载了 2 个号码: 13800000001, 13800000002")
    print(f"当前黑名单总数: {bm.size}")

    test_phones = [
        ("13800000001", True, "标准格式 - 精确匹配"),
        ("１３８０００００００１", True, "全角数字 - 应过滤"),
        ("+86 138-0000-0001", True, "+86前缀 - 应过滤"),
        ("008613800000001", True, "0086前缀 - 应过滤"),
        ("8613800000001", True, "86前缀 - 应过滤"),
        ("１３８－００００－０００１", True, "全角横杠 - 应过滤"),
        ("（＋８６）１３８　００００　０００１", True, "全角括号空格 - 应过滤"),
        ("Abc138xyz0000test0001", True, "混入字母大小写 - 应过滤"),
        ("ABC138XYZ0000TEST0002", True, "全大写字母 - 应过滤2号"),
        ("13900000003", False, "非黑名单号码"),
        ("13300000004", False, "非黑名单号码2"),
    ]

    all_passed = True
    for phone, should_blacklist, desc in test_phones:
        is_bl = bm.is_blacklisted(phone)
        passed = is_bl == should_blacklist
        all_passed = all_passed and passed
        status = "✅" if passed else "❌"
        normalized = PhoneValidator.normalize(phone)
        print(f"{status} [{desc}]")
        print(f"   原始: {phone!r}")
        print(f"   归一化后: {normalized}")
        print(f"   判定黑名单: {is_bl} (期望: {should_blacklist})")

    return all_passed


async def test_batch_with_edge_cases():
    print("\n" + "=" * 60)
    print("测试批量发送（含各种边界格式）")
    print("=" * 60)

    service = SmsService(rate_per_second=100.0)
    service.blacklist.add("13800000001")
    service.blacklist.add("13800000002")
    print(f"黑名单: {service.blacklist.size} 个号码")

    phones = [
        "13800000001",
        "１３８０００００００１",
        "+86 138-0000-0002",
        "008613800000002",
        "13900000003",
        "１３８－００００－０００４",
        "Abc138xyz0000test0005",
        "12345678901",
        "13100000008",
        "（＋８６）１３８　００００　０００９",
    ]

    content = "【测试】验证码 888888"
    report = await service.send_batch(phones, content)

    print(f"\n发送报告:")
    print(f"  总计: {report.total}")
    print(f"  成功: {report.success}")
    print(f"  黑名单: {report.blacklisted}")
    print(f"  无效: {report.invalid}")
    print(f"  失败: {report.failed}")
    print(f"  耗时: {report.duration:.3f}s")

    expected_blacklist = 4
    expected_invalid = 1
    expected_success = 5

    print(f"\n期望黑名单数: {expected_blacklist}, 实际: {report.blacklisted}")
    print(f"期望无效号码数: {expected_invalid}, 实际: {report.invalid}")
    print(f"期望成功数: {expected_success}, 实际: {report.success}")

    all_passed = (report.blacklisted == expected_blacklist and
                  report.invalid == expected_invalid and
                  report.success == expected_success)

    if all_passed:
        print("✅ 批量测试通过!")
    else:
        print("❌ 批量测试失败!")
        print("\n详细结果:")
        for r in report.results:
            print(f"  [{r.status.value}] {r.phone} - {r.message}")

    return all_passed


async def main():
    results = []
    results.append(("normalize 归一化测试", test_phone_normalize()))
    results.append(("validate 验证测试", test_phone_validate()))
    results.append(("blacklist 黑名单过滤测试", test_blacklist_filtering()))
    results.append(("batch 批量发送测试", await test_batch_with_edge_cases()))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    all_ok = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} - {name}")
        all_ok = all_ok and passed

    print("\n" + ("全部测试通过!" if all_ok else "存在测试失败!"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
