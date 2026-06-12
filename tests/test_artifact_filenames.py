from backend.services.agent_builder import agent_file_slug, artifact_download_filename


def test_agent_file_slug():
    assert agent_file_slug("Sara") == "sara"
    assert agent_file_slug("Finance Bot") == "finance_bot"


def test_artifact_download_filenames():
    assert artifact_download_filename("agent_skill_md", "Sara") == "sara_skill.md"
    assert artifact_download_filename("agent_framework_json", "Sara") == "sara_agent_framework.json"
