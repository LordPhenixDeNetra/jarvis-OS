from __future__ import annotations

from pathlib import Path

from memory.index import MemoryIndex
from memory.sessions import SessionStore
from memory.topics import TopicStore

# ── SessionStore ──────────────────────────────────────────────

def test_session_store_append_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.append("abc-123", "user", "Bonjour")
    store.append("abc-123", "assistant", "Salut chef.")

    messages = store.load("abc-123")
    assert len(messages) == 2
    assert messages[0] == {"role": "user", "content": "Bonjour"}
    assert messages[1] == {"role": "assistant", "content": "Salut chef."}


def test_session_store_load_unknown(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    assert store.load("does-not-exist") == []


def test_session_store_creates_dated_file(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    store.append("uuid-xyz", "user", "Test")

    files = list(sessions_dir.glob("*_uuid-xyz.jsonl"))
    assert len(files) == 1
    # Fichier nommé YYYY-MM-DD_uuid-xyz.jsonl
    assert files[0].name.endswith("_uuid-xyz.jsonl")


def test_session_store_list_recent(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.append("s1", "user", "A")
    store.append("s2", "user", "B")
    recent = store.list_recent(n=5)
    assert len(recent) == 2


# ── MemoryIndex ───────────────────────────────────────────────

def test_memory_index_read(tmp_path: Path) -> None:
    md = tmp_path / "MEMORY.md"
    md.write_text("# Index\n\n## Utilisateur\n- profile: `topics/user.md` — Barth\n")
    idx = MemoryIndex(tmp_path)
    content = idx.read()
    assert "profile" in content


def test_memory_index_add_pointer_new_section(tmp_path: Path) -> None:
    md = tmp_path / "MEMORY.md"
    md.write_text("# Index\n")
    idx = MemoryIndex(tmp_path)
    idx.add_pointer("Projets actifs", "ipod", "topics/project_ipod.md", "DAP iPod PCM5102A")

    content = md.read_text()
    assert "ipod" in content
    assert "project_ipod.md" in content
    assert "DAP iPod PCM5102A" in content


def test_memory_index_update_existing_pointer(tmp_path: Path) -> None:
    md = tmp_path / "MEMORY.md"
    md.write_text("# Index\n\n## Projets actifs\n- ipod: `topics/old.md` — Ancienne description\n")
    idx = MemoryIndex(tmp_path)
    idx.add_pointer("Projets actifs", "ipod", "topics/project_ipod.md", "Nouvelle description")

    content = md.read_text()
    assert "Nouvelle description" in content
    assert "Ancienne description" not in content
    # Un seul pointeur ipod
    assert content.count("- ipod:") == 1


def test_memory_index_add_pointer_existing_section(tmp_path: Path) -> None:
    md = tmp_path / "MEMORY.md"
    initial = "# Index\n\n## Projets actifs\n- jarvis: `topics/jarvis.md` — Jarvis\n\n## Autre\n"
    md.write_text(initial)
    idx = MemoryIndex(tmp_path)
    idx.add_pointer("Projets actifs", "alfred", "topics/alfred.md", "Bras robotisé")

    content = md.read_text()
    assert "alfred" in content
    assert "Bras robotisé" in content


# ── TopicStore ────────────────────────────────────────────────

def test_topic_store_write_and_load(tmp_path: Path) -> None:
    store = TopicStore(tmp_path / "topics")
    store.write("project_ipod.md", "# iPod DAP\n\nPCM5102A, DAC haute qualité.")
    content = store.load("project_ipod.md")
    assert "PCM5102A" in content


def test_topic_store_load_all(tmp_path: Path) -> None:
    store = TopicStore(tmp_path / "topics")
    store.write("a.md", "# A")
    store.write("b.md", "# B")
    all_topics = store.load_all()
    assert set(all_topics.keys()) == {"a.md", "b.md"}


def test_topic_store_load_unknown(tmp_path: Path) -> None:
    store = TopicStore(tmp_path / "topics")
    assert store.load("inexistant.md") == ""


def test_topic_store_exists(tmp_path: Path) -> None:
    store = TopicStore(tmp_path / "topics")
    assert not store.exists("x.md")
    store.write("x.md", "# X")
    assert store.exists("x.md")


# ── Session persist callback ───────────────────────────────────

def test_session_persist_callback(tmp_path: Path) -> None:
    from core.session import Session

    written: list[tuple[str, str]] = []

    session = Session()
    session.set_persist(lambda role, content: written.append((role, content)))

    session.add_message("user", "Test persist")
    session.add_message("assistant", "Reçu.")

    assert written == [("user", "Test persist"), ("assistant", "Reçu.")]


def test_session_manager_restore_from_jsonl(tmp_path: Path) -> None:
    from core.session import SessionManager
    from memory.sessions import SessionStore

    # UUID valide requis — les sessions sont toujours identifiées par uuid4()
    session_id = "12345678-1234-5678-1234-567812345678"
    store = SessionStore(tmp_path / "sessions")
    store.append(session_id, "user", "Je travaille sur l'iPod DAP")
    store.append(session_id, "assistant", "Noté, iPod DAP avec PCM5102A.")

    mgr = SessionManager(store=store)
    session = mgr.get_or_create(session_id)

    assert len(session.messages) == 2
    assert session.messages[0]["content"] == "Je travaille sur l'iPod DAP"
