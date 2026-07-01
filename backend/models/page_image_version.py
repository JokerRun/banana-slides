"""
Page Image Version model - stores historical versions of generated images
"""

import uuid
import json
from datetime import datetime
from . import db


class PageImageVersion(db.Model):
    """
    Page Image Version model - represents a historical version of a page's generated image
    """

    __tablename__ = "page_image_versions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_id = db.Column(
        db.String(36), db.ForeignKey("pages.id"), nullable=False, index=True
    )
    image_path = db.Column(db.String(500), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)  # 版本号，从1开始递增
    is_current = db.Column(
        db.Boolean, nullable=False, default=False
    )  # 是否为当前使用的版本
    prompt_snapshot = db.Column(
        db.Text, nullable=True
    )  # 生成该版本时的最终 provider prompt
    ref_manifest = db.Column(db.Text, nullable=True)  # JSON: 生成/编辑上下文参考图清单
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    page = db.relationship("Page", back_populates="image_versions")

    def to_dict(self):
        """Convert to dictionary"""
        # Get project_id from page relationship
        project_id = self.page.project_id if self.page else None
        # Format created_at with UTC timezone indicator for proper frontend parsing
        created_at_str = None
        if self.created_at:
            # Add 'Z' suffix to indicate UTC timezone, so frontend can parse it correctly
            created_at_str = (
                self.created_at.isoformat() + "Z"
                if not self.created_at.tzinfo
                else self.created_at.isoformat()
            )
        return {
            "version_id": self.id,
            "page_id": self.page_id,
            "image_path": self.image_path,
            "image_url": (
                f'/files/{project_id}/pages/{self.image_path.split("/")[-1]}'
                if self.image_path and project_id
                else None
            ),
            "version_number": self.version_number,
            "is_current": self.is_current,
            "prompt_snapshot": self.prompt_snapshot,
            "ref_manifest": self.get_ref_manifest(),
            "created_at": created_at_str,
        }

    def get_ref_manifest(self):
        """Parse ref_manifest JSON string."""
        if self.ref_manifest:
            try:
                return json.loads(self.ref_manifest)
            except json.JSONDecodeError:
                return []
        return []

    def set_ref_manifest(self, data):
        """Set ref_manifest as JSON string."""
        self.ref_manifest = json.dumps(data or [], ensure_ascii=False)

    def __repr__(self):
        return f"<PageImageVersion {self.id}: page={self.page_id}, version={self.version_number}, current={self.is_current}>"
