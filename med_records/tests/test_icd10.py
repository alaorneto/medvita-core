"""The global ICD-10 table: loaded by the operator's command, searched by everyone with the app active."""

import pytest
from django.core.management import CommandError, call_command

from skeleton.service_api import InvalidInput

from ..models import Icd10Code
from ..service_api import RecordsService
from .helpers import prepare

SAMPLE = """code;description
J45;Asma
J45.0;Asma predominantemente alérgica
J45.1;Asma não-alérgica
I10;Hipertensão essencial (primária)
E11;Diabetes mellitus não-insulino-dependente
E11.9;Diabetes mellitus não-insulino-dependente - sem complicações
A00;Cólera
A00.0;Cólera devida a Vibrio cholerae 01, biótipo cholerae
A01;Febres tifóide e paratifóide
A01.0;Febre tifóide
B20;Doença pelo HIV resultando em doenças infecciosas e parasitárias
C50;Neoplasia maligna da mama
F32;Episódios depressivos
F32.9;Episódio depressivo não especificado
G43;Enxaqueca
K29;Gastrite e duodenite
M54.5;Dor lombar baixa
N39.0;Infecção do trato urinário de localização não especificada
R51;Cefaléia
Z00.0;Exame médico geral
"""


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "cid10.csv"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def test_load_is_idempotent_and_validated(skeleton_db, sample, tmp_path, capsys):
    call_command("load_icd10", str(sample))
    assert Icd10Code.objects.count() == 0
    call_command("load_icd10", str(sample), "--confirm")
    assert Icd10Code.objects.count() == 20 and "20 created" in capsys.readouterr().out
    call_command("load_icd10", str(sample), "--confirm")
    assert "0 created, 0 updated" in capsys.readouterr().out
    assert Icd10Code.objects.get(code="J45").is_category and not Icd10Code.objects.get(code="J45.0").is_category
    broken = tmp_path / "broken.csv"
    broken.write_text("X99;Outro\nJ4;Errado\n", encoding="utf-8")
    with pytest.raises(CommandError, match="Line 2"):
        call_command("load_icd10", str(broken), "--confirm")
    assert not Icd10Code.objects.filter(code="X99").exists()


def test_search_by_code_and_words(clinic, sample):
    ready = prepare(clinic)
    call_command("load_icd10", str(sample), "--confirm")
    for side, organization in ((ready.a, ready.org_a), (ready.b, ready.org_b)):
        with ready.as_user(side.reception, organization) as actor:
            assert [item.code for item in RecordsService().search_icd10(actor=actor, query="J45")] == [
                "J45",
                "J45.0",
                "J45.1",
            ]
            assert {
                item.code for item in RecordsService().search_icd10(actor=actor, query="asma predominantemente")
            } == {"J45.0"}
            assert RecordsService().search_icd10(actor=actor, query="cefaleia")[0].code == "R51"
    with ready.as_user(ready.a.doctor) as doctor:
        for query, limit in (("", 20), ("asma", 0), ("asma", 51)):
            with pytest.raises(InvalidInput):
                RecordsService().search_icd10(actor=doctor, query=query, limit=limit)
