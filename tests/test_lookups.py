import pytest
from unittest.mock import patch


def test_icd10_valid_code(tmp_path):
    csv_content = "code,description\nJ06.9,Acute upper resp infection unspecified\nZ00.00,Encounter adult exam without complaint\n"
    icd_file = tmp_path / "icd10.csv"
    icd_file.write_text(csv_content)

    with patch("claimflow.lookups.icd10._CSV_PATH", icd_file):
        from claimflow.lookups.icd10 import is_valid_icd10, _reset
        _reset()
        assert is_valid_icd10("J06.9") is True
        assert is_valid_icd10("J069") is True   # dot-stripped variant
        assert is_valid_icd10("XXXXX") is False


def test_cpt_valid_code(tmp_path):
    csv_content = "code,description\n99213,Office visit established patient moderate\n99214,Office visit established patient mod-high\n"
    cpt_file = tmp_path / "cpt.csv"
    cpt_file.write_text(csv_content)

    with patch("claimflow.lookups.cpt._CSV_PATH", cpt_file):
        from claimflow.lookups.cpt import is_valid_cpt, _reset
        _reset()
        assert is_valid_cpt("99213") is True
        assert is_valid_cpt("00000") is False
