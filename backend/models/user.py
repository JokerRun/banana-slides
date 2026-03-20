"""User model."""

import uuid
from datetime import datetime

from . import db


class User(db.Model):
    """Authenticated user identity."""

    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name = db.Column(db.Text, nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    oauth_accounts = db.relationship(
        'UserOAuthAccount',
        back_populates='user',
        lazy='select',
        cascade='all, delete-orphan',
    )
    projects = db.relationship('Project', back_populates='owner', lazy='select')
    user_templates = db.relationship('UserTemplate', back_populates='owner', lazy='select')
    materials = db.relationship('Material', back_populates='owner', lazy='select')
    tasks = db.relationship('Task', back_populates='owner', lazy='select')
    reference_files = db.relationship('ReferenceFile', back_populates='owner', lazy='select')

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'display_name': self.display_name,
            'avatar_url': self.avatar_url,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<User {self.id}: active={self.is_active}>'
