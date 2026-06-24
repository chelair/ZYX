"""
项目数据持久化 — vaspcheck_projects.json 的读写

所有脚本通过此模块统一访问项目数据库，消除 5 处重复定义。
"""
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECTS_FILE = SKILL_DIR / "vaspcheck_projects.json"


def load_projects():
    """加载项目数据库"""
    if not PROJECTS_FILE.exists():
        print(f"[X] 找不到项目文件: {PROJECTS_FILE}")
        print("请先用 project_manager.py 添加项目")
        sys.exit(1)
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_projects(projects):
    """保存项目数据库"""
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)


def find_project(projects, name):
    """在项目列表中按名称查找"""
    for p in projects:
        if p["name"] == name:
            return p
    return None


def find_subtask(project, name):
    """在项目的子任务列表中按名称查找"""
    for s in project.get("subs", []):
        if s["name"] == name:
            return s
    return None