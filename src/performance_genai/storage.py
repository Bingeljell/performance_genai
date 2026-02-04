from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from performance_genai.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_filename(name: str) -> str:
    # Prevent path traversal; keep it simple for v0.
    return os.path.basename(name).replace("..", "_")


@dataclass(frozen=True)
class Asset:
    asset_id: str
    kind: str  # reference|product|kv|master|other
    filename: str
    rel_path: str
    sha256: str
    created_at: str
    metadata: dict[str, Any]


@dataclass
class Project:
    project_id: str
    name: str
    brand_name: str | None
    campaign_name: str | None
    created_at: str
    assets: list[Asset]
    observed_profile: dict[str, Any] | None


class ProjectStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or settings.data_dir).resolve()
        self.projects_dir = self.root_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str, brand_name: str | None = None, campaign_name: str | None = None) -> Project:
        project_id = uuid.uuid4().hex[:12]
        proj_dir = self.projects_dir / project_id
        (proj_dir / "assets").mkdir(parents=True, exist_ok=True)
        (proj_dir / "motifs").mkdir(parents=True, exist_ok=True)
        (proj_dir / "profiles").mkdir(parents=True, exist_ok=True)
        (proj_dir / "kvs").mkdir(parents=True, exist_ok=True)
        (proj_dir / "masters").mkdir(parents=True, exist_ok=True)
        (proj_dir / "layouts").mkdir(parents=True, exist_ok=True)
        (proj_dir / "text_previews").mkdir(parents=True, exist_ok=True)
        (proj_dir / "runs").mkdir(parents=True, exist_ok=True)

        proj = Project(
            project_id=project_id,
            name=name,
            brand_name=(brand_name or "").strip() or None,
            campaign_name=(campaign_name or "").strip() or None,
            created_at=_now_iso(),
            assets=[],
            observed_profile=None,
        )
        self._write_project(proj)
        return proj

    def list_projects(self) -> list[Project]:
        out: list[Project] = []
        for proj_dir in sorted(self.projects_dir.glob("*")):
            if not proj_dir.is_dir():
                continue
            try:
                out.append(self.read_project(proj_dir.name))
            except Exception:
                # Ignore corrupted projects for v0.
                continue
        return out

    def read_project(self, project_id: str) -> Project:
        proj_path = self.projects_dir / project_id / "project.json"
        data = json.loads(proj_path.read_text("utf-8"))
        assets = [Asset(**a) for a in data.get("assets", [])]
        return Project(
            project_id=data["project_id"],
            name=data["name"],
            brand_name=data.get("brand_name"),
            campaign_name=data.get("campaign_name"),
            created_at=data["created_at"],
            assets=assets,
            observed_profile=data.get("observed_profile"),
        )

    def delete_project(self, project_id: str) -> None:
        proj_dir = (self.projects_dir / project_id).resolve()
        if not str(proj_dir).startswith(str(self.projects_dir.resolve()) + os.sep):
            raise ValueError("Refusing to delete outside projects_dir")
        if proj_dir.exists():
            shutil.rmtree(proj_dir)

    def delete_asset(self, project_id: str, asset_id: str) -> None:
        proj = self.read_project(project_id)
        remaining: list[Asset] = []
        removed: list[Asset] = []
        for a in proj.assets:
            if a.asset_id == asset_id:
                removed.append(a)
            else:
                remaining.append(a)
        if not removed:
            return

        proj.assets = remaining
        self._write_project(proj)

        for a in removed:
            path = self.abs_asset_path(project_id, a)
            try:
                path.unlink(missing_ok=True)
            except Exception:
                # Best-effort deletion in v0.
                pass

    def update_asset_metadata(self, project_id: str, asset_id: str, updates: dict[str, Any]) -> None:
        proj = self.read_project(project_id)
        changed = False
        refreshed: list[Asset] = []
        for a in proj.assets:
            if a.asset_id != asset_id:
                refreshed.append(a)
                continue
            new_meta = dict(a.metadata or {})
            new_meta.update(updates)
            refreshed.append(
                Asset(
                    asset_id=a.asset_id,
                    kind=a.kind,
                    filename=a.filename,
                    rel_path=a.rel_path,
                    sha256=a.sha256,
                    created_at=a.created_at,
                    metadata=new_meta,
                )
            )
            changed = True
        if changed:
            proj.assets = refreshed
            self._write_project(proj)

    def add_asset(
        self,
        project_id: str,
        kind: str,
        filename: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
        subdir: str = "assets",
    ) -> Asset:
        proj_dir = self.projects_dir / project_id
        asset_id = uuid.uuid4().hex[:12]
        filename = _safe_filename(filename)

        out_dir = proj_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        rel_path = str(Path(subdir) / f"{asset_id}_{filename}")
        abs_path = proj_dir / rel_path
        abs_path.write_bytes(content)

        asset = Asset(
            asset_id=asset_id,
            kind=kind,
            filename=filename,
            rel_path=rel_path,
            sha256=_sha256_file(abs_path),
            created_at=_now_iso(),
            metadata=metadata or {},
        )

        proj = self.read_project(project_id)
        proj.assets.append(asset)
        self._write_project(proj)
        return asset

    def abs_asset_path(self, project_id: str, asset: Asset) -> Path:
        return self.projects_dir / project_id / asset.rel_path

    def write_observed_profile(self, project_id: str, profile: dict[str, Any]) -> None:
        proj_dir = self.projects_dir / project_id
        (proj_dir / "profiles" / "observed_profile.json").write_text(
            json.dumps(profile, indent=2),
            encoding="utf-8",
        )
        proj = self.read_project(project_id)
        proj.observed_profile = profile
        self._write_project(proj)

    def write_run_manifest(self, project_id: str, manifest: dict[str, Any]) -> Path:
        proj_dir = self.projects_dir / project_id
        run_id = uuid.uuid4().hex[:12]
        path = proj_dir / "runs" / f"run_{run_id}.json"
        manifest = dict(manifest)
        manifest.setdefault("run_id", run_id)
        manifest.setdefault("created_at", _now_iso())
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def _write_project(self, proj: Project) -> None:
        proj_dir = self.projects_dir / proj.project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        path = proj_dir / "project.json"
        data = asdict(proj)
        data["assets"] = [asdict(a) for a in proj.assets]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
