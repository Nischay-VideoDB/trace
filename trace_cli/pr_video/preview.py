"""Generate animated GIF preview from an HLS URL and host it via PR repo.

GitHub does not embed HLS or mp4 in PR comments via the API. GIFs do
auto-embed via standard markdown `![](url)`. Approach:
  1. ffmpeg HLS URL -> ~10s GIF (320 wide, 10 fps).
  2. Upload GIF as a GitHub release asset on the PR's repo.
     Release assets get a stable `releases/download/<tag>/<name>` URL
     that PR comments will render inline as image / animated GIF.
  3. Return the asset URL so PR comment can embed it.

Fallback: if release upload fails, return None and caller posts plain link.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from github import Auth, Github, GithubException
from github.GitReleaseAsset import GitReleaseAsset

log = logging.getLogger("trace.pr_video.preview")


def render_preview_gif(hls_url: str, *, out_path: Path, seconds: float = 10.0, width: int = 480, fps: int = 12) -> Path | None:
    """ffmpeg HLS -> GIF. Returns out_path on success, None on failure."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("ffmpeg not found; cannot render preview gif")
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    palette = out_path.with_suffix(".palette.png")
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-t", str(seconds), "-i", hls_url,
             "-vf", f"{vf},palettegen=stats_mode=diff", str(palette)],
            check=True, capture_output=True, timeout=120,
        )
        subprocess.run(
            [ffmpeg, "-y", "-t", str(seconds), "-i", hls_url, "-i", str(palette),
             "-lavfi", f"{vf} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5",
             str(out_path)],
            check=True, capture_output=True, timeout=120,
        )
        palette.unlink(missing_ok=True)
    except subprocess.CalledProcessError as e:
        log.warning("ffmpeg gif gen failed: %s", (e.stderr or b"")[-400:].decode(errors="ignore"))
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg gif gen timed out")
        return None
    if not out_path.exists() or out_path.stat().st_size == 0:
        return None
    log.info("preview gif: %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path


def render_thumbnail(hls_url: str, *, out_path: Path, at_seconds: float = 5.0, width: int = 720) -> Path | None:
    """ffmpeg HLS -> single JPG thumbnail. Returns out_path on success."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("ffmpeg not found; cannot render thumbnail")
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [ffmpeg, "-y", "-ss", str(at_seconds), "-i", hls_url,
             "-frames:v", "1",
             "-vf", f"scale={width}:-1:flags=lanczos",
             "-q:v", "3",
             str(out_path)],
            check=True, capture_output=True, timeout=60,
        )
    except subprocess.CalledProcessError as e:
        log.warning("ffmpeg thumb gen failed: %s", (e.stderr or b"")[-400:].decode(errors="ignore"))
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg thumb gen timed out")
        return None
    if not out_path.exists() or out_path.stat().st_size == 0:
        return None
    log.info("thumbnail: %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path


def upload_image_as_release_asset(
    image_path: Path,
    *,
    owner: str,
    repo: str,
    tag: str,
    content_type: str = "image/jpeg",
    token: str | None = None,
) -> str | None:
    """Generic image upload to a release. Replaces existing asset with same name."""
    return _upload_asset(image_path, owner=owner, repo=repo, tag=tag, content_type=content_type, token=token)


def _upload_asset(
    asset_path: Path,
    *,
    owner: str,
    repo: str,
    tag: str,
    content_type: str,
    token: str | None = None,
) -> str | None:
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        log.warning("no GITHUB_TOKEN; skipping release upload")
        return None
    gh = Github(auth=Auth.Token(token))
    try:
        r = gh.get_repo(f"{owner}/{repo}")
    except GithubException as e:
        log.warning("repo lookup failed: %s", e)
        return None
    release = None
    try:
        release = r.get_release(tag)
    except GithubException:
        try:
            release = r.create_git_release(
                tag=tag,
                name="trace previews",
                message="auto-generated PR previews from trace",
                draft=False,
                prerelease=True,
            )
        except GithubException as e:
            log.warning("release create failed: %s", e)
            return None
    asset_name = asset_path.name
    try:
        for a in release.get_assets():
            if a.name == asset_name:
                a.delete_asset()
                break
        asset: GitReleaseAsset = release.upload_asset(
            path=str(asset_path), label=asset_name, content_type=content_type,
        )
    except GithubException as e:
        log.warning("asset upload failed: %s", e)
        return None
    url = asset.browser_download_url
    log.info("uploaded asset: %s", url)
    return url


def upload_gif_as_release_asset(gif_path: Path, *, owner: str, repo: str, tag: str, token: str | None = None) -> str | None:
    return _upload_asset(gif_path, owner=owner, repo=repo, tag=tag, content_type="image/gif", token=token)
