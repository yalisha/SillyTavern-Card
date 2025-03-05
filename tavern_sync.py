#!/usr/bin/env python3
from pathlib import Path
from typing import List
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile


def load_config(config_path: Path) -> dict:
    """Load the JSON configuration file"""
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def confirm_action(action):
    """Ask the user to confirm the action before proceeding"""
    response = input(f"你确定要{action}? (yes/no): ").strip().lower()
    return response == "yes"


class Entry:
    def __init__(self, title: str, file: Path, content: str, spaces: str, type: str):
        self.title = title
        self.file = file
        self.content = content
        self.spaces = spaces
        self.type = type


def extract_file_content(file_path: Path, user_name: str) -> str:
    """Read the content of a file and return it as a string"""
    content = file_path.read_text(encoding="utf-8")
    if user_name and user_name in content:
        content = content.replace(user_name, "<user>")
        file_path.write_text(content, encoding="utf-8")
        print(f"{file_path}: 已替换 {user_name} 为 <user>")
    return content


def trim_json(text: str) -> str:
    def replace_func(match):
        if match.group(1):
            return match.group(1)
        elif match.group(2):
            return match.group(3)

    return re.sub(r'("[^"]*")|(\s+)(//.*\n)?', replace_func, text)


def to_flow_yaml(path: Path) -> str:
    return subprocess.run(
        ["yq", '.. style="flow"', str(path)],
        check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8").stdout


def split_yaml_entries(path: Path, content: str, should_trim: bool) -> List[Entry]:
    """Split content into entries based on regex matches"""
    if should_trim:
        content = to_flow_yaml(path)

    entries = []
    pattern = re.compile(r"( *)\# \^([^\n]+)\n([\s\S]*?)((?= *\# \^[^\n]+\n)|\Z)", re.MULTILINE)
    for match in pattern.finditer(content):
        spaces, title, entry_content = match.group(1), match.group(2), match.group(3)
        entries.append(Entry(title=title, file=path, content=entry_content, spaces=spaces, type="yaml"))
    return entries


def split_json_entries(path: Path, content: str, should_trim: bool) -> List[Entry]:
    """Split content into entries based on regex matches"""
    entries = []
    pattern = re.compile(r"( *)\/\/ \^([^\n]+)\n([\s\S]*?)((?= *\/\/ \^[^\n]+\n)|\Z)", re.MULTILINE)
    for match in pattern.finditer(content):
        spaces, title, entry_content = match.group(1), match.group(2), match.group(3)
        if should_trim:
            entry_content = trim_json(entry_content)
        entries.append(Entry(title=title, file=path, content=entry_content, spaces=spaces, type="json"))
    return entries


def read_entries(directory: Path, should_trim: bool, user_name: str) -> List[Entry]:
    """Read and return entries from all files in a directory"""
    entries = []
    for path in directory.rglob("*"):
        if path.is_file() and path.name != ".DS_Store" and not path.stem.endswith("!"):
            content = extract_file_content(path, user_name)
            if path.stem.endswith("合集"):
                if path.suffix == ".yaml":
                    if content.startswith("# ^"):
                        entries.extend(split_yaml_entries(path, content, should_trim))
                    else:
                        print(f"错误: 解析 '{path}' 出错, 你是不是忘了在开头加一行 '# ^条目名' 告知该部分内容是属于哪个条目")
                        exit(1)
                elif path.suffix == ".json":
                    if content.startswith("// ^"):
                        entries.extend(split_json_entries(path, content, should_trim))
                    else:
                        print(f"错误: 解析 '{path}' 出错, 你是不是忘了在开头加一行 '// ^条目名' 告知该部分内容是属于哪个条目")
                        exit(1)
                continue

            if should_trim:
                if path.suffix == ".json":
                    content = trim_json(content)
                if path.suffix == ".yaml":
                    content = to_flow_yaml(path)
            entries.append(Entry(title=path.stem, file=path, content=content, spaces="", type="normal"))
    return entries


def write_entries(entries: List[Entry]):
    """Write entries to their respective files"""
    from itertools import groupby
    entries.sort(key=lambda x: x.file)

    for file, grouped_entries in groupby(entries, key=lambda x: x.file):
        content = ""
        entry_list = list(grouped_entries)
        type = entry_list[0].type
        if type == 'normal':
            content = entry_list[0].content
        else:
            for entry in entry_list:
                content += f"{entry.spaces}{'//' if entry.type == 'json' else '#'} ^{entry.title}\n{entry.content}"

        file.write_text(content, encoding="utf-8")


def read_json(json_file: Path) -> dict:
    """Read and return JSON data from a file"""
    with json_file.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(json_file: Path, data: dict):
    """Write JSON data to a file with indentation"""
    with json_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def push(directory: Path, json_file: Path, user_name: str, should_trim: bool):
    """Push file contents from directory into JSON entries"""
    if not confirm_action("将文件推送到世界书"):
        print("取消推送")
        return

    entries = read_entries(directory, should_trim, user_name)
    json_data = read_json(json_file)

    unused_entries = set(entries)
    for entry in json_data.get("entries").values():
        title = entry.get("comment")
        matching_entry = next((e for e in entries if e.title == title), None)

        if matching_entry is None:
            print(f"错误: 未找到世界书中条目 '{title}' 对应的文件")
            exit(1)

        entry["content"] = matching_entry.content
        unused_entries.discard(matching_entry)
    if unused_entries:
        print("错误: 未能在世界书中找到以下条目")
        for entry in unused_entries:
            print(f"- '{entry.title}': '{entry.file}'")
        exit(1)

    write_json(json_file, json_data)
    print("成功推送")


def format_jsons(directory: Path):
    json_files = [str(json_path) for json_path in directory.rglob("*.json")]
    if json_files:
        try:
            subprocess.run(["clang-format", "-i"] + json_files, check=True, encoding="utf-8")
        except subprocess.CalledProcessError as e:
            print(f"格式化 json 失败: {e}")


def format_yamls(directory: Path):
    yaml_files = [str(yaml_path) for yaml_path in directory.rglob("**/*.yaml")]
    for yaml_file in yaml_files:
        try:
            subprocess.run(["yq", '... style=""', "-i", yaml_file], check=True, encoding="utf-8")
        except subprocess.CalledProcessError as e:
            print(f"格式化 yaml 失败: {e}")


def pull(directory: Path, json_file: Path, user_name: str):
    """Pull content from JSON entries and write to files in directory"""
    if not confirm_action("将世界书拉取到文件"):
        print("取消拉取")
        return

    entries = read_entries(directory, user_name, False)
    json_data = read_json(json_file)

    for entry in json_data.get("entries").values():
        title = entry.get("comment")
        matching_entry = next((e for e in entries if e.title == title), None)
        if matching_entry is None:
            print(f"错误: 未找到世界书中条目 '{title}' 对应的文件")
            exit(1)

        matching_entry.content = entry.get("content", "")

    write_entries(entries)
    format_jsons(directory)
    format_yamls(directory)
    print("成功拉取")


def is_valid_file(content: str, extension: str):
    try:
        subprocess.run(["yq", "-p", extension.removeprefix('.'), "-"], check=True,
                       input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        return True
    except subprocess.CalledProcessError:
        return False


def is_valid_json(content: str):
    return is_valid_file(content, ".json")


def is_valid_yaml(content: str):
    return is_valid_file(content, ".yaml")


def extract(output_directory: Path, json_file: Path, detect: bool):
    """Extract content from JSON entries to a directory"""
    if not output_directory.exists():
        os.makedirs(output_directory)

    if len(os.listdir(output_directory)) != 0:
        print(f"错误: 进行提取操作时, 配置文件中设定的独立文件文件夹 directory ({output_directory}) 必须为空文件夹!")
        exit(1)

    if not confirm_action(f"将 {json_file} 提取到 {output_directory}"):
        print("取消提取")
        return

    json_data = read_json(json_file)

    for entry in json_data.get("entries").values():
        title = entry.get("comment")
        if sys.platform in ['win32', 'cygwin'] and any(char in title for char in '\\/:*?"<>|'):
            print(f'错误: 不能创建 \'${title}\' 文件, Windows 上文件不能包含以下任何字符: \\/:*?"<>|')
            exit(1)
        if sys.platform == 'darwin' and ':' in title:
            print(f'错误: 不能创建 \'${title}\' 文件, MacOS 上文件不能包含 : 字符')
            exit(1)
        if sys.platform == 'linux' and '/' in title:
            print(f'错误: 不能创建 \'${title}\' 文件, Linux 上文件不能包含 / 字符')
            exit(1)
        content = entry.get("content").strip()
        extension = ".md"

        if detect:
            if content.startswith("```json") and content.endswith("```"):
                content = content.removeprefix("```json").removesuffix("```").strip()
                extension = ".json"
            elif content.startswith("```yaml") and content.endswith("```"):
                content = content.removeprefix("```yaml").removesuffix("```").strip()
                extension = ".yaml"
            elif content:
                if is_valid_json(content):
                    extension = ".json"
                elif is_valid_yaml(content):
                    extension = ".yaml"

        file_path = os.path.join(output_directory, f"{title}{extension}")
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)

    if detect:
        format_jsons(output_directory)
        format_yamls(output_directory)
    print("成功提取")


def convert_extension(directory: Path, old: str, new: str):
    """Convert all `old` extension files in a directory to `new` extension"""
    if not confirm_action(f"将 {directory} 中所有 {old} 文件转换为 {new} 文件"):
        print("取消转换")
        return

    for path in directory.rglob("*"):
        if path.is_file():
            if path.suffix == old:
                try:
                    subprocess.run(
                        ["yq", '.. style=""', "-p", old.removeprefix('.'),
                         "-o", new.removeprefix('.'),
                         "-i", str(path)],
                        check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8").stdout
                    os.rename(path, path.with_suffix(new))
                except subprocess.CalledProcessError:
                    continue


def to_json(directory: Path):
    convert_extension(directory, ".yaml", ".json")


def to_yaml(directory: Path):
    convert_extension(directory, ".json", ".yaml")


def load_or_create_config(config_path: Path) -> dict:
    """Load the JSON configuration file, or create an empty one if it doesn't exist"""
    if not config_path.exists():
        config_path.write_text("{}", encoding="utf-8")
        return {}

    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def publish(
        publish_directory: Path, character_card: Path, quick_replies: list[Path],
        lorebook_directory: Path, script_directory: Path = None):
    """Publish cards into publish_directory"""
    publish_directory.mkdir(parents=True, exist_ok=True)  # Ensure directory exists

    quick_replies_text = [f"\n  - {qr}" for qr in quick_replies]
    response = input(f"""你确定要将以下文件发布到 {publish_directory} 文件夹下?
- 世界书源文件: {lorebook_directory}
- 角色卡: {character_card}
- 前端助手源文件: {script_directory if script_directory is not None else "无"}
- 快速回复: {"".join(quick_replies_text) if quick_replies else "无"}
(yes/no): """).strip().lower()
    if response != "yes":
        print("取消发布")
        exit(1)

    # Copy character_card
    try:
        shutil.copy(character_card, publish_directory)
        print(f"已复制角色卡到 {publish_directory}")
    except Exception as e:
        print(f"错误: 复制角色卡失败, {e}")
        exit(1)

    # Copy quick_replies
    if quick_replies:
        try:
            for qr in quick_replies:
                shutil.copy(qr, publish_directory)
            print(f"已复制快速回复到 {publish_directory}")
        except Exception as e:
            print(f"错误: 复制快速回复, {e}")
            exit(1)

    # Zip directory into 世界书源文件.zip
    try:
        directory_zip = publish_directory / "世界书源文件.zip"
        with zipfile.ZipFile(directory_zip, 'w') as zf:
            for file in lorebook_directory.rglob('*'):  # Recursively add all files
                if file.name != '.DS_Store':
                    zf.write(file, Path("世界书源文件") / file.relative_to(lorebook_directory))

            readme_content = """\
世界书因为是同步过去后脚本自动省token的，在酒馆里可能比较难看，因此发了源文件**。
可以直接看文件，也可以配着用 https://sillytavern-stage-girls-dog.readthedocs.io/tool_and_experience/lorebook_script/index.html 查看。\
"""
            zf.writestr("使用说明.txt", readme_content)

        print(f"已压缩目录为 {directory_zip}")
    except Exception as e:
        print(f"错误: 压缩目录失败, {e}")
        exit(1)

    # Zip directory into 前端正则源文件.zip
    if script_directory is not None:
        try:
            directory_zip = publish_directory / "前端助手源文件.zip"
            with zipfile.ZipFile(directory_zip, 'w') as zf:
                for file in script_directory.rglob('*'):  # Recursively add all files
                    if file.name != '.DS_Store':
                        zf.write(file, Path("前端助手源文件") / file.relative_to(script_directory))

                readme_content = """\
    前端助手的脚本是用 TypeScript 写再自动编译成酒馆可用的 JavaScript 的，在酒馆里可能比较难看，因此发了源文件**。
    可以直接看文件，也可以配着用 https://sillytavern-stage-girls-dog.readthedocs.io/tool_and_experience/js_slash_runner/index.html 查看。\
    """
                zf.writestr("使用说明.txt", readme_content)

            print(f"已压缩目录为 {directory_zip}")
        except Exception as e:
            print(f"错误: 压缩目录失败, {e}")
            exit(1)

    print("成功发布")


def main():
    config = load_or_create_config(Path(__file__).parent / "tavern_sync_config.json")

    parser = argparse.ArgumentParser(description="分文件修改世界书脚本, 具体说明请查看: ")

    subparsers = parser.add_subparsers(dest="command")

    extract_parser = subparsers.add_parser("extract", help="将世界书提取成独立文件")
    extract_parser.add_argument("card_name", choices=config.keys(), help="配置文件中填写的世界书名称")
    extract_parser.add_argument("--no_detect", action="store_true", help="启用时, 提取世界书时不会检测条目内容格式并自动转换为 json 或 yaml")

    push_parser = subparsers.add_parser("push", help="将独立文件推送到世界书的条目中 (如果没有找到与世界书条目名匹配的文件会报错) (如果你正在用酒馆, 推送后请记得刷新网页)")
    push_parser.add_argument("card_name", choices=config.keys(), help="配置文件中填写的世界书名称")
    push_parser.add_argument("--no_trim", action="store_true", help="启用时, 推送到世界书时将不会删除空白符来节省 token")

    pull_parser = subparsers.add_parser("pull", help="将世界书中的条目拉取到独立文件中 (如果没有找到与世界书条目名匹配的文件会报错)")
    pull_parser.add_argument("card_name", choices=config.keys(), help="配置文件中填写的世界书名称")

    publish_parser = subparsers.add_parser("publish", help="将世界书中的条目拉取到独立文件中 (如果没有找到与世界书条目名匹配的文件会报错)")
    publish_parser.add_argument("card_name", choices=config.keys(), help="配置文件中填写的世界书名称")

    to_json_parser = subparsers.add_parser("to_json", help="将独立文件中 .yaml 文件转换为 .json 文件, 转换过程中 '#' 开头的注释会丢失")
    to_json_parser.add_argument("card_name", choices=config.keys(), help="配置文件中填写的世界书名称")

    to_yaml_parser = subparsers.add_parser(
        "to_yaml", help="将独立的文件中 .json 文件转换为 .yaml 文件, 不能转换带注释 ('// comment' 或 '/* comment */') 的 json")
    to_yaml_parser.add_argument("card_name", choices=config.keys(), help="配置文件中填写的世界书名称")

    args = parser.parse_args()

    name_to_args = config[args.card_name]
    directory = Path(name_to_args["directory"])
    if directory.exists() and not directory.is_dir():
        print(f"错误: 配置文件中设定的独立文件文件夹 directory ({directory}) 必须是一个文件夹")
        exit(1)

    json_file = Path(name_to_args["json_file"])
    if not json_file.exists():
        print(f"错误: 配置文件中设定的世界书文件 json_file ({json_file}) 不存在")
        exit(1)

    if args.command == "extract":
        extract(directory, json_file, not args.no_detect)
        return

    if not directory.exists():
        print(f"错误: 配置文件中设定的独立文件文件夹 directory ({directory}) 不存在")
        exit(1)

    user_name = name_to_args.get("user_name")

    if args.command == "push":
        push(directory, json_file, user_name, not args.no_trim)
    elif args.command == "pull":
        pull(directory, json_file, user_name)
    elif args.command == "publish":
        publish_directory = Path(name_to_args["publish_directory"])

        character_card = Path(name_to_args["character_card"])
        if not os.path.isfile(character_card):
            print(f"错误: 配置文件中设定的角色卡文件 character_card ({character_card}) 不存在")
            exit(1)

        quick_replies = [Path(qr) for qr in name_to_args.get("quick_replies", [])]
        inexist_quick_replies = []
        for quick_reply in quick_replies:
            if not os.path.isfile(quick_reply):
                inexist_quick_replies.append(quick_reply)
        if inexist_quick_replies:
            print("错误: 未能找到以下快速回复")
            for quick_reply in quick_replies:
                print(f"- {quick_reply}")
            exit(1)

        publish(publish_directory, character_card, quick_replies, directory, Path(
            name_to_args["script_directory"]) if "script_directory" in name_to_args else None)
    elif args.command == "to_json":
        to_json(directory)
    elif args.command == "to_yaml":
        to_yaml(directory)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
