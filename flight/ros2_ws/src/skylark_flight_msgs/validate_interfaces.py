#!/usr/bin/env python3
"""静态校验 ROS 2 接口定义（.msg / .srv / .action）与 package.xml / CMakeLists.txt 的一致性。

用途：在没有 ROS 2 环境的机器上（例如 Windows 飞控开发机）先把语法与命名错误挡掉，
避免到 WSL2 里 colcon build 才发现问题。

不替代 colcon build —— 它不做类型解析和跨包依赖检查。

用法:
    python validate_interfaces.py
退出码: 0 = 全部通过, 1 = 有错误
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent

PRIMITIVES = {
    "bool", "byte", "char",
    "float32", "float64",
    "int8", "uint8", "int16", "uint16",
    "int32", "uint32", "int64", "uint64",
    "string", "wstring",
}

# 允许的类型写法：
#   基本类型 / 包名/类型 / 同包类型
#   数组后缀 []  [N]  [<=N]
#   有界字符串 string<=N
TYPE_RE = re.compile(
    r"^(?P<base>[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)?)"
    r"(?P<bound><=\d+)?"
    r"(?P<array>\[(?:\d+|<=\d+)?\])?$"
)
FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CONST_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# 常量赋值：类型之后紧跟 '<名字> =' 才算常量。
# 用于把 'uint8 FOO=1'（常量）与 'string<=32 name'（有界字符串字段）区分开。
CONST_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def check_section(path: Path, section_name: str, lines: list[tuple[int, str]]) -> None:
    """校验一个消息段（msg 全文 / srv 的请求或响应 / action 的 goal/result/feedback）。"""
    seen_fields: dict[str, int] = {}
    seen_consts: dict[str, int] = {}

    for lineno, raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        # 常量与字段的区分：常量的 '=' 紧跟在名字之后。
        # 不能简单用 '=' in line 判断 —— 有界字符串 'string<=32 name' 的类型里也含 '='。
        split_type = line.split(None, 1)
        remainder = split_type[1] if len(split_type) > 1 else ""
        is_constant = bool(CONST_ASSIGN_RE.match(remainder))

        # ---- 常量：TYPE NAME=value ----
        if is_constant:
            head, _, value = line.partition("=")
            parts = head.split()
            if len(parts) != 2:
                err(f"{path.name}:{lineno} [{section_name}] 常量格式应为 '<type> <NAME>=<value>'，实际: {line!r}")
                continue
            ctype, cname = parts
            m = TYPE_RE.match(ctype)
            if not m:
                err(f"{path.name}:{lineno} [{section_name}] 常量类型非法: {ctype!r}")
            elif m.group("array"):
                err(f"{path.name}:{lineno} [{section_name}] 常量不能是数组: {ctype!r}")
            elif m.group("base") not in PRIMITIVES:
                err(f"{path.name}:{lineno} [{section_name}] 常量只能是基本类型，实际: {ctype!r}")
            if not CONST_NAME_RE.match(cname):
                err(f"{path.name}:{lineno} [{section_name}] 常量名必须全大写下划线: {cname!r}")
            if not value.strip():
                err(f"{path.name}:{lineno} [{section_name}] 常量缺少值: {line!r}")
            if cname in seen_consts:
                err(f"{path.name}:{lineno} [{section_name}] 常量名重复 {cname!r}（首现于第 {seen_consts[cname]} 行）")
            else:
                seen_consts[cname] = lineno
            continue

        # ---- 字段：type name [default] ----
        parts = line.split(None, 2)
        if len(parts) < 2:
            err(f"{path.name}:{lineno} [{section_name}] 字段至少需要 '<type> <name>'，实际: {line!r}")
            continue

        ftype, fname = parts[0], parts[1]
        m = TYPE_RE.match(ftype)
        if not m:
            err(f"{path.name}:{lineno} [{section_name}] 类型写法非法: {ftype!r}")
        else:
            base = m.group("base")
            if "/" not in base and base not in PRIMITIVES:
                # 同包自定义类型：必须存在对应 .msg 文件
                if not (PKG_DIR / "msg" / f"{base}.msg").exists():
                    err(f"{path.name}:{lineno} [{section_name}] 引用了不存在的同包类型 {base!r}"
                        f"（未找到 msg/{base}.msg）")
            if m.group("bound") and base != "string":
                err(f"{path.name}:{lineno} [{section_name}] 只有 string 支持 <=N 上界，实际: {ftype!r}")

        if not FIELD_NAME_RE.match(fname):
            err(f"{path.name}:{lineno} [{section_name}] 字段名必须小写下划线且以字母开头: {fname!r}")
        if fname in seen_fields:
            err(f"{path.name}:{lineno} [{section_name}] 字段名重复 {fname!r}（首现于第 {seen_fields[fname]} 行）")
        else:
            seen_fields[fname] = lineno

        if fname in seen_consts:
            err(f"{path.name}:{lineno} [{section_name}] 字段名与常量名冲突: {fname!r}")


def split_sections(path: Path, expected_separators: int) -> list[list[tuple[int, str]]] | None:
    numbered = [(i, ln.rstrip("\n")) for i, ln in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)]
    sep_indices = [idx for idx, (_, ln) in enumerate(numbered) if ln.strip() == "---"]
    if len(sep_indices) != expected_separators:
        err(f"{path.name} 分隔符 '---' 数量应为 {expected_separators}，实际 {len(sep_indices)}")
        return None
    sections: list[list[tuple[int, str]]] = []
    start = 0
    for idx in sep_indices:
        sections.append(numbered[start:idx])
        start = idx + 1
    sections.append(numbered[start:])
    return sections


def check_package_xml() -> set[str]:
    path = PKG_DIR / "package.xml"
    if not path.exists():
        err("package.xml 不存在")
        return set()
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        err(f"package.xml XML 语法错误: {exc}")
        return set()

    if root.get("format") != "3":
        warn(f"package.xml format 建议为 3，实际 {root.get('format')!r}")

    for tag in ("name", "version", "description", "maintainer", "license"):
        if root.find(tag) is None:
            err(f"package.xml 缺少必需元素 <{tag}>")

    name_el = root.find("name")
    if name_el is not None and name_el.text != PKG_DIR.name:
        err(f"package.xml 中 <name>{name_el.text}</name> 与目录名 {PKG_DIR.name!r} 不一致")

    lic = root.find("license")
    if lic is not None and lic.text and "AGPL" not in lic.text:
        warn(f"package.xml license 为 {lic.text!r}，仓库根 LICENSE 是 AGPL-3.0，确认是否有意不同")

    groups = [g.text for g in root.findall("member_of_group")]
    if "rosidl_interface_packages" not in groups:
        err("package.xml 缺少 <member_of_group>rosidl_interface_packages</member_of_group>，接口包必需")

    buildtools = {b.text for b in root.findall("buildtool_depend")}
    if "rosidl_default_generators" not in buildtools:
        err("package.xml 缺少 <buildtool_depend>rosidl_default_generators</buildtool_depend>")

    execdeps = {e.text for e in root.findall("exec_depend")}
    if "rosidl_default_runtime" not in execdeps:
        err("package.xml 缺少 <exec_depend>rosidl_default_runtime</exec_depend>")

    declared = {d.text for d in root.findall("depend")} | buildtools | execdeps
    return declared


def check_cmakelists(interface_files: set[str], declared_deps: set[str]) -> None:
    path = PKG_DIR / "CMakeLists.txt"
    if not path.exists():
        err("CMakeLists.txt 不存在")
        return
    text = path.read_text(encoding="utf-8-sig")

    if "rosidl_generate_interfaces" not in text:
        err("CMakeLists.txt 未调用 rosidl_generate_interfaces()")
        return

    listed = set(re.findall(r'"((?:msg|srv|action)/[^"]+)"', text))

    missing_in_cmake = interface_files - listed
    for f in sorted(missing_in_cmake):
        err(f"CMakeLists.txt 未登记接口文件: {f}")

    missing_on_disk = listed - interface_files
    for f in sorted(missing_on_disk):
        err(f"CMakeLists.txt 登记了不存在的文件: {f}")

    # DEPENDENCIES 里出现的包必须在 package.xml 声明过
    dep_block = re.search(r"DEPENDENCIES(.*?)\)", text, re.S)
    if dep_block:
        for dep in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", dep_block.group(1)):
            if dep and dep not in declared_deps:
                err(f"CMakeLists.txt DEPENDENCIES 中的 {dep!r} 未在 package.xml 声明")

    if "action" in {f.split("/")[0] for f in interface_files} and "action_msgs" not in declared_deps:
        err("包含 action 定义但 package.xml 未依赖 action_msgs")


def main() -> int:
    declared_deps = check_package_xml()

    interface_files: set[str] = set()
    counts = {"msg": 0, "srv": 0, "action": 0}

    for sub, ext, seps in (("msg", ".msg", 0), ("srv", ".srv", 1), ("action", ".action", 2)):
        d = PKG_DIR / sub
        if not d.is_dir():
            continue
        for path in sorted(d.glob(f"*{ext}")):
            interface_files.add(f"{sub}/{path.name}")
            counts[sub] += 1
            if seps == 0:
                numbered = [
                    (i, ln) for i, ln in
                    enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
                ]
                if any(ln.strip() == "---" for _, ln in numbered):
                    err(f"{path.name} 是 .msg，不应含 '---' 分隔符")
                check_section(path, "msg", numbered)
            else:
                sections = split_sections(path, seps)
                if sections is None:
                    continue
                names = (["request", "response"] if seps == 1
                         else ["goal", "result", "feedback"])
                for name, sec in zip(names, sections):
                    check_section(path, name, sec)

    check_cmakelists(interface_files, declared_deps)

    print(f"接口文件统计: msg={counts['msg']}  srv={counts['srv']}  action={counts['action']}"
          f"  合计={sum(counts.values())}")

    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")

    if errors:
        print(f"\n失败: {len(errors)} 个错误, {len(warnings)} 个警告")
        return 1
    print(f"\n通过: 0 个错误, {len(warnings)} 个警告")
    print("注意: 本校验不替代 colcon build。到 WSL2 后请执行真实构建确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
