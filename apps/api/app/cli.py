"""관리 명령.

    python -m app.cli create-user <아이디> [--admin] [--name 이름]     # 비밀번호는 입력 프롬프트
    python -m app.cli import-users users.csv                          # username,display_name,password[,role]
"""
import argparse
import csv
import getpass
import sys

from sqlalchemy import select

from .config import get_settings
from .db import Database
from .models import User
from .security import hash_password


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    cu = sub.add_parser("create-user", help="사용자 생성 (이미 있으면 비밀번호/권한 갱신)")
    cu.add_argument("username")
    cu.add_argument("--name", default="")
    cu.add_argument("--admin", action="store_true")

    iu = sub.add_parser("import-users", help="CSV 로 사용자 일괄 등록")
    iu.add_argument("csv_path")

    args = p.parse_args(argv)
    db_ = Database(get_settings().database_url)
    db_.create_all()
    db = db_.SessionLocal()

    try:
        if args.cmd == "create-user":
            pw = getpass.getpass("비밀번호: ")
            if len(pw) < 8 or pw != getpass.getpass("비밀번호 확인: "):
                print("비밀번호가 8자 미만이거나 일치하지 않습니다", file=sys.stderr)
                return 1
            u = db.scalar(select(User).where(User.username == args.username)) or User(username=args.username)
            u.display_name = args.name or u.display_name or ""
            u.role = "admin" if args.admin else (u.role or "student")
            u.password_hash = hash_password(pw)
            u.is_active = True
            db.add(u)
            db.commit()
            print(f"저장됨: {u.username} ({u.role})")

        elif args.cmd == "import-users":
            n = 0
            with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    username = (row.get("username") or "").strip()
                    password = (row.get("password") or "").strip()
                    if not username or len(password) < 8:
                        print(f"건너뜀: {username or '?'} (비밀번호 8자 미만)", file=sys.stderr)
                        continue
                    u = db.scalar(select(User).where(User.username == username)) or User(username=username)
                    u.display_name = (row.get("display_name") or "").strip()
                    u.role = "admin" if (row.get("role") or "").strip() == "admin" else "student"
                    u.password_hash = hash_password(password)
                    db.add(u)
                    n += 1
            db.commit()
            print(f"{n}명 저장됨")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
