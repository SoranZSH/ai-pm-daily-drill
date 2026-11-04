"""M6 调度脚本的静态检查（离线）。

真正的 schtasks 注册、触发与卸载只能在 Windows 上验收（方案 M6 验收步骤）；这里检查容器中可以验证的部分：
- 安装脚本中的任务 XML 模板（替换占位符后）结构正确：3 个触发器、设置、动作、权限；
- 两个 .ps1 带 UTF-8 BOM（Windows PowerShell 5.1 需要）；
- 立即采集.bat 的命令；
- 安装与卸载使用同一个任务名。
"""
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.dirname(HERE)
sys.path.insert(0, COLLECTOR)

NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
TASK_NAME = "Github学习-采集"
SAMPLE = {
    "START": "2026-10-11",
    "USER": "PC\\tester",
    "PYTHONW": r"C:\Python311\pythonw.exe",
    "DIR": r"D:\Download\面试英语题库\Github学习\collector",
}


def read_text(name: str) -> str:
    with open(os.path.join(COLLECTOR, name), "rb") as f:
        return f.read().decode("utf-8-sig")


def read_bytes(name: str) -> bytes:
    with open(os.path.join(COLLECTOR, name), "rb") as f:
        return f.read()


def task_xml(**overrides) -> str:
    """从安装脚本取出 XML 模板，按 PowerShell 端的方式替换占位符（值做 XML 转义）。"""
    m = re.search(r"\$xmlTemplate = @'\r?\n(.*?)\r?\n'@", read_text("安装定时任务.ps1"), re.S)
    assert m, "安装脚本中找不到 $xmlTemplate"
    xml = m.group(1)
    values = dict(SAMPLE, **overrides)
    for key, val in values.items():
        xml = xml.replace("{{%s}}" % key, escape(val))
    assert "{{" not in xml, "仍有未替换的占位符"
    return xml


def parse(xml: str) -> ET.Element:
    body = xml.split("\n", 1)[1]        # 去掉 XML 声明（声明为 UTF-16，文件以 UTF-16 写出）
    return ET.fromstring(body)


def local(tag: str) -> str:
    return tag.split("}", 1)[-1]


class TaskXmlTest(unittest.TestCase):
    def setUp(self):
        self.root = parse(task_xml())

    def find(self, path: str):
        node = self.root
        for part in path.split("/"):
            node = node.find(NS + part)
            assert node is not None, f"缺少节点 {path}"
        return node

    def text(self, path: str) -> str:
        return (self.find(path).text or "").strip()

    def test_declaration_is_utf16(self):
        xml = task_xml()
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-16"?>'))

    def test_four_triggers_in_order(self):
        kinds = [local(t.tag) for t in self.find("Triggers")]
        self.assertEqual(kinds, ["CalendarTrigger", "LogonTrigger", "CalendarTrigger", "EventTrigger"])

    def test_wake_from_sleep_event_trigger(self):
        ev = list(self.find("Triggers"))[3]
        self.assertEqual(ev.find(NS + "Enabled").text, "true")
        self.assertEqual(ev.find(NS + "Delay").text, "PT1M")
        sub = ev.find(NS + "Subscription").text
        self.assertIn("Path=\"System\"", sub)
        self.assertIn("Microsoft-Windows-Power-Troubleshooter", sub)
        self.assertIn("EventID=1", sub)
        # 订阅本身必须是合法 XML（转义后的 QueryList）
        ET.fromstring(sub)

    def test_does_not_wake_computer_and_has_no_idle_conditions(self):
        self.assertEqual(self.text("Settings/WakeToRun"), "false")
        self.assertIsNone(self.find("Settings").find(NS + "IdleSettings"))

    def test_daily_0900_without_repetition(self):
        first = list(self.find("Triggers"))[0]
        self.assertEqual(first.find(NS + "StartBoundary").text, "2026-10-11T09:00:00")
        self.assertEqual(first.find(NS + "ScheduleByDay/" + NS + "DaysInterval").text, "1")
        self.assertIsNone(first.find(NS + "Repetition"))

    def test_hourly_repetition_for_14_hours_from_0900(self):
        third = list(self.find("Triggers"))[2]
        rep = third.find(NS + "Repetition")
        self.assertIsNotNone(rep)
        self.assertEqual(rep.find(NS + "Interval").text, "PT1H")
        self.assertEqual(rep.find(NS + "Duration").text, "PT14H")
        self.assertEqual(third.find(NS + "StartBoundary").text, "2026-10-11T09:00:00")

    def test_logon_trigger_with_5_minute_delay_for_current_user(self):
        logon = list(self.find("Triggers"))[1]
        self.assertEqual(logon.find(NS + "Delay").text, "PT5M")
        self.assertEqual(logon.find(NS + "UserId").text, SAMPLE["USER"])

    def test_settings_match_plan(self):
        self.assertEqual(self.text("Settings/MultipleInstancesPolicy"), "IgnoreNew")
        self.assertEqual(self.text("Settings/StartWhenAvailable"), "true")       # 错过计划后尽快运行
        self.assertEqual(self.text("Settings/DisallowStartIfOnBatteries"), "false")  # 不要求交流电
        self.assertEqual(self.text("Settings/StopIfGoingOnBatteries"), "false")
        self.assertEqual(self.text("Settings/ExecutionTimeLimit"), "PT1H")        # 执行时间上限 1 小时

    def test_action_runs_pythonw_collect_in_collector_dir(self):
        self.assertTrue(self.text("Actions/Exec/Command").lower().endswith("pythonw.exe"))
        self.assertEqual(self.text("Actions/Exec/Arguments"), "collect.py")
        self.assertEqual(self.text("Actions/Exec/WorkingDirectory"), SAMPLE["DIR"])

    def test_runs_as_current_user_without_admin(self):
        self.assertEqual(self.text("Principals/Principal/LogonType"), "InteractiveToken")
        self.assertEqual(self.text("Principals/Principal/RunLevel"), "LeastPrivilege")
        self.assertEqual(self.text("Principals/Principal/UserId"), SAMPLE["USER"])

    def test_special_characters_in_paths_survive_escaping(self):
        odd = r"D:\A&B <test>\collector"
        root = parse(task_xml(DIR=odd))
        wd = root.find(f"{NS}Actions/{NS}Exec/{NS}WorkingDirectory").text
        self.assertEqual(wd, odd)


class ScriptFilesTest(unittest.TestCase):
    def test_ps1_files_have_utf8_bom(self):
        for name in ("安装定时任务.ps1", "卸载定时任务.ps1"):
            self.assertEqual(read_bytes(name)[:3], b"\xef\xbb\xbf", name)

    def test_batch_runs_collect_with_force_then_pauses(self):
        text = read_text("立即采集.bat")
        self.assertIn('cd /d "%~dp0"', text)
        self.assertIn("python collect.py --force", text)
        self.assertIn("pause", text)

    def test_install_and_uninstall_use_same_task_name(self):
        self.assertIn(f'$taskName = "{TASK_NAME}"', read_text("安装定时任务.ps1"))
        self.assertIn(f'$taskName = "{TASK_NAME}"', read_text("卸载定时任务.ps1"))

    def test_uninstall_deletes_task_with_force(self):
        self.assertIn("schtasks /Delete /TN $taskName /F", read_text("卸载定时任务.ps1"))

    def test_install_resolves_pythonw_path(self):
        self.assertIn("Get-Command pythonw.exe", read_text("安装定时任务.ps1"))


if __name__ == "__main__":
    unittest.main()
