"""내부보관용: 자전거 외 부품(헬멧·보호대) 제외 테스트. 실행: python -I tests/test_storage_exclude.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import storage as S  # noqa: E402

cfg = S.load_cfg()
assert S.is_excluded("삼천리SH700어린이어반헬멧/라이트핑크", cfg)
assert S.is_excluded("삼천리SPS110어린이보호대/블루/2개", cfg)
assert S.is_excluded("삼천리 SH700 어린이 헬멧", cfg)
assert not S.is_excluded("시애틀F26/블랙", cfg)
assert not S.is_excluded(None, cfg)
assert not S.is_excluded("시애틀F26/블랙", {})
print("OK")
