"""User OAuth account model."""

import uuid
from datetime import datetime

from . import db


class UserOAuthAccount(db.Model):
    """External OAuth identity bound to an internal user."""

    __tablename__ = 'user_oauth_accounts'
    __table_args__ = (
        db.UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user_id'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False, index=True)
    provider_user_id = db.Column(db.String(255), nullable=False, index=True)
    provider_username = db.Column(db.String(255), nullable=True)
    email_at_provider = db.Column(db.String(255), nullable=True)
    raw_profile = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', back_populates='oauth_accounts')

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'provider': self.provider,
            'provider_user_id': self.provider_user_id,
            'provider_username': self.provider_username,
            'email_at_provider': self.email_at_provider,
            'raw_profile': self.raw_profile,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<UserOAuthAccount {self.provider}:{self.provider_user_id}>'
