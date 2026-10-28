import os

from backend.app.core.environment import load_environment


def test_load_environment_reads_env_file_without_overriding_process_values(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KNOWLEDGEOPS_TEST_FROM_FILE=loaded\n"
        "KNOWLEDGEOPS_TEST_PRECEDENCE=file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("KNOWLEDGEOPS_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("KNOWLEDGEOPS_TEST_PRECEDENCE", "process")

    load_environment(env_file)

    assert os.environ["KNOWLEDGEOPS_TEST_FROM_FILE"] == "loaded"
    assert os.environ["KNOWLEDGEOPS_TEST_PRECEDENCE"] == "process"
