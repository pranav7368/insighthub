"""The legal pack.

These are drafts awaiting counsel, so the tests do not check legal correctness —
they cannot. They check the two things that go wrong mechanically:

  * a document quietly contradicts the product (a stated retention period the
    software does not enforce, a subprocessor that is not listed);
  * an unfinished draft gets published with placeholders still in it.

The second is the one that actually happens.
"""

import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
LEGAL = ROOT / "docs" / "legal"
TEMPLATES = LEGAL / "templates"

DOCUMENTS = ["PRIVACY_POLICY.md", "TERMS_OF_SERVICE.md", "DPA.md",
             "SUBPROCESSORS.md", "INCIDENT_RESPONSE.md"]


@pytest.fixture(scope="module")
def values():
    raw = json.loads((LEGAL / "company.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@pytest.fixture(scope="module")
def texts():
    return {name: (TEMPLATES / name).read_text(encoding="utf-8") for name in DOCUMENTS}


# ------------------------------------------------------------ structure ---

def test_every_document_exists():
    for name in DOCUMENTS:
        assert (TEMPLATES / name).exists(), f"{name} is missing"


def test_every_token_used_is_defined(values, texts):
    """A token with no value renders as literal {{MUSTACHE}} on a public page."""
    used = set()
    for text in texts.values():
        used |= set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text))
    undefined = sorted(used - set(values))
    assert not undefined, f"company.json does not define: {undefined}"


def test_no_unused_values(values, texts):
    """An unused value is a fact someone will keep updating for nothing."""
    blob = "\n".join(texts.values())
    unused = sorted(k for k in values if f"{{{{{k}}}}}" not in blob)
    assert not unused, f"defined but never used: {unused}"


# ------------------------------------- claims we must not accidentally make --

@pytest.mark.parametrize("name", DOCUMENTS)
def test_no_compliance_claims(name, texts):
    """Compliance is a property of an organisation and an audit, never of a
    codebase. Claiming it without one is false and loses enterprise deals."""
    text = texts[name].lower()
    for phrase in ["we are gdpr compliant", "we are dpdp compliant",
                   "fully compliant", "soc 2 certified", "iso 27001 certified",
                   "is gdpr-compliant", "100% secure", "completely secure"]:
        assert phrase not in text, f"{name} claims {phrase!r}"


def test_security_is_described_as_reasonable_not_absolute(texts):
    privacy = texts["PRIVACY_POLICY.md"]
    assert "No service can promise perfect security" in privacy


def test_the_dpa_admits_we_hold_no_audit_report(texts):
    """Better said plainly than implied otherwise and discovered in diligence."""
    assert "do not currently hold a SOC 2" in texts["DPA.md"]


# ------------------------------- documents must match what the code does ----

def test_subprocessor_list_matches_the_real_data_flows(texts):
    """Every outbound flow in the product appears in the list.

    An omitted subprocessor is a contractual breach and the first thing a
    security reviewer checks against your configuration.
    """
    subs = texts["SUBPROCESSORS.md"]
    for flow in ["LLM_PROVIDER", "PAYMENT_PROCESSOR", "ERROR_TRACKING", "HOSTING_PROVIDER"]:
        assert f"{{{{{flow}}}}}" in subs, f"{flow} is not listed as a subprocessor"


def test_privacy_policy_states_the_ai_boundary_correctly(texts):
    """The single most misunderstood fact about this product: the model sees
    the question and the schema, never the rows."""
    privacy = texts["PRIVACY_POLICY.md"]
    assert "rows of your data are not sent" in privacy
    assert "offline mode" in privacy


def test_no_training_on_customer_data_is_promised_everywhere(texts):
    """If we say it once we must say it consistently — a customer will quote
    whichever document is most favourable to them."""
    for name in ("PRIVACY_POLICY.md", "TERMS_OF_SERVICE.md", "DPA.md"):
        assert "train" in texts[name].lower(), f"{name} does not address AI training"


def test_retention_is_driven_by_configuration_not_prose(texts):
    """A stated period the product does not enforce is worse than none."""
    privacy = texts["PRIVACY_POLICY.md"]
    assert "{{RETENTION_AUDIT_DAYS}}" in privacy
    assert "{{RETENTION_DATA_DAYS}}" in privacy


def test_data_subject_rights_match_the_endpoints_that_exist(texts):
    """Each right promised has a mechanism behind it."""
    privacy = texts["PRIVACY_POLICY.md"]
    for promised in ["Download my data", "delete", "correct"]:
        assert promised.lower() in privacy.lower(), f"{promised} is promised nowhere"


def test_incident_runbook_carries_the_real_deadlines(texts):
    runbook = texts["INCIDENT_RESPONSE.md"]
    assert "72 hours" in runbook            # GDPR supervisory authority
    assert "48 hours" in runbook            # our own DPA commitment to customers
    assert "Data Protection Board" in runbook
    # the DPA promise and the runbook must not disagree
    assert "48 hours" in texts["DPA.md"]


# ----------------------------------------------------------- publishing ---

def test_build_script_reports_unfinished_drafts():
    """--check must FAIL while placeholders remain. This is what stops a draft
    reaching a website; if it ever passes with TODOs, the guard is useless."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_legal.py"), "--check"],
        capture_output=True, text=True,
    )
    values = json.loads((LEGAL / "company.json").read_text(encoding="utf-8"))
    has_todos = any(str(v).strip().startswith("TODO")
                    for k, v in values.items() if not k.startswith("_"))
    if has_todos:
        assert result.returncode != 0, "--check passed despite unfilled placeholders"
        assert "NOT ready to publish" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def test_dev_values_can_never_be_published():
    """The load-bearing property of --dev.

    Development placeholders exist so the pages can be linked and read while
    building, without a lawyer. If they could satisfy the publish gate, "we'll
    fill it in later" would quietly become the live policy — which is exactly
    how a fake company address ends up on a real website.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_legal.py"), "--dev", "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "--dev must never pass the publish gate"
    assert "never publishable" in result.stderr


def test_dev_build_is_unmistakably_marked():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_legal.py"), "--dev"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    for name in DOCUMENTS:
        text = (LEGAL / "build" / name).read_text(encoding="utf-8")
        assert "DEVELOPMENT BUILD — NOT A REAL POLICY" in text
        assert "PLACEHOLDERS, NOT REAL" in text


def test_dev_values_are_obviously_fake():
    """Nobody should be able to mistake a placeholder for a real detail —
    and the reserved .invalid domain means a stray script cannot email a real
    person by accident (RFC 2606)."""
    dev = json.loads((LEGAL / "company.dev.json").read_text(encoding="utf-8"))
    for key, value in dev.items():
        if key.endswith("_EMAIL") or key in ("CONTACT_EMAIL",):
            assert value.endswith(".invalid"), f"{key} must use a reserved domain"
    assert "NOT A REAL ENTITY" in dev["COMPANY_LEGAL_NAME"]


def test_dev_and_real_value_files_stay_in_step():
    """A token added to one must be added to the other, or --dev breaks the
    day someone needs it."""
    real = json.loads((LEGAL / "company.json").read_text(encoding="utf-8"))
    dev = json.loads((LEGAL / "company.dev.json").read_text(encoding="utf-8"))
    strip = lambda d: {k for k in d if not k.startswith("_")}   # noqa: E731
    assert strip(real) == strip(dev), (
        f"only in company.json: {strip(real) - strip(dev)}; "
        f"only in company.dev.json: {strip(dev) - strip(real)}"
    )


def test_build_script_renders_all_documents(tmp_path, monkeypatch):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_legal.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    build = LEGAL / "build"
    for name in DOCUMENTS:
        rendered = (build / name).read_text(encoding="utf-8")
        assert "GENERATED — do not edit" in rendered
        assert "Reviewed by counsel: NO" in rendered
