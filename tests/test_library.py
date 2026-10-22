import pytest

from app import library


def test_lists_only_video_files(videos_dir):
    (videos_dir / "b.mp4").write_bytes(b"x")
    (videos_dir / "A.mov").write_bytes(b"xy")
    (videos_dir / "notes.txt").write_text("not a video")
    (videos_dir / "folder.mp4").mkdir()

    videos = library.list_videos()
    assert [v["name"] for v in videos] == ["A.mov", "b.mp4"]
    assert videos[0] == {"name": "A.mov", "size_bytes": 2, "duration_seconds": 60.0}


def test_missing_folder_lists_nothing(videos_dir):
    videos_dir.rmdir()
    assert library.list_videos() == []


def test_resolve_finds_a_video(videos_dir):
    (videos_dir / "my clip.mp4").write_bytes(b"x")
    assert library.resolve("my clip.mp4") == (videos_dir / "my clip.mp4").resolve()


@pytest.mark.parametrize("name", ["missing.mp4", "../secret.mp4", "..\\secret.mp4", "notes.txt", ""])
def test_resolve_rejects_unknown_or_unsafe_names(videos_dir, name):
    (videos_dir.parent / "secret.mp4").write_bytes(b"x")
    (videos_dir / "notes.txt").write_text("x")
    with pytest.raises(library.VideoNotFound):
        library.resolve(name)
