# 文档模型
from datetime import datetime
from app import db

# 文档标签关联表
document_tags = db.Table('document_tags',
    db.Column('document_id', db.Integer, db.ForeignKey('documents.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)

class Document(db.Model):
    """文档模型"""
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    content = db.Column(db.Text)
    summary = db.Column(db.Text)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    status = db.Column(db.Enum('draft', 'published', 'archived'), default='draft')
    visibility = db.Column(db.Enum('public', 'private', 'department'), default='public')
    view_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    comment_count = db.Column(db.Integer, default=0)
    version = db.Column(db.Integer, default=1)
    is_pinned = db.Column(db.Boolean, default=False)
    is_featured = db.Column(db.Boolean, default=False)
    allow_comment = db.Column(db.Boolean, default=True)
    meta_data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    
    # 关系
    category = db.relationship('Category', backref='documents')
    tags = db.relationship('Tag', secondary=document_tags, backref='documents')
    comments = db.relationship('Comment', backref='document', lazy='dynamic')
    versions = db.relationship('DocumentVersion', backref='document', lazy='dynamic')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'summary': self.summary,
            'author': self.author.to_dict() if self.author else None,
            'category': self.category.to_dict() if self.category else None,
            'tags': [tag.to_dict() for tag in self.tags],
            'status': self.status,
            'visibility': self.visibility,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'comment_count': self.comment_count,
            'version': self.version,
            'is_pinned': self.is_pinned,
            'is_featured': self.is_featured,
            'allow_comment': self.allow_comment,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'published_at': self.published_at.isoformat() if self.published_at else None
        }
    
    def __repr__(self):
        return f'<Document {self.title}>'

class Category(db.Model):
    """分类模型"""
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    level = db.Column(db.Integer, default=1)
    sort_order = db.Column(db.Integer, default=0)
    icon = db.Column(db.String(50))
    color = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    document_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    children = db.relationship('Category', backref=db.backref('parent', remote_side=[id]))
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'parent_id': self.parent_id,
            'level': self.level,
            'sort_order': self.sort_order,
            'icon': self.icon,
            'color': self.color,
            'is_active': self.is_active,
            'document_count': self.document_count,
            'children': [child.to_dict() for child in self.children]
        }
    
    def __repr__(self):
        return f'<Category {self.name}>'

class Tag(db.Model):
    """标签模型"""
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    color = db.Column(db.String(20), default='#409EFF')
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'color': self.color,
            'usage_count': self.usage_count
        }
    
    def __repr__(self):
        return f'<Tag {self.name}>'

class Comment(db.Model):
    """评论模型"""
    __tablename__ = 'comments'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'))
    content = db.Column(db.Text, nullable=False)
    like_count = db.Column(db.Integer, default=0)
    status = db.Column(db.Enum('active', 'hidden', 'deleted'), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = db.relationship('User', backref='comments')
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]))
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'document_id': self.document_id,
            'user': self.user.to_dict() if self.user else None,
            'parent_id': self.parent_id,
            'content': self.content,
            'like_count': self.like_count,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'replies': [reply.to_dict() for reply in self.replies]
        }
    
    def __repr__(self):
        return f'<Comment {self.id}>'

class DocumentVersion(db.Model):
    """文档版本模型"""
    __tablename__ = 'document_versions'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    change_summary = db.Column(db.Text)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系
    author = db.relationship('User', backref='document_versions')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'document_id': self.document_id,
            'version': self.version,
            'title': self.title,
            'content': self.content,
            'change_summary': self.change_summary,
            'author': self.author.to_dict() if self.author else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<DocumentVersion {self.document_id} v{self.version}>'