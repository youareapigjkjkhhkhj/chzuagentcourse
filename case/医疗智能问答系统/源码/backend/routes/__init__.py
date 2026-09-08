#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由模块
"""

from .auth import auth_bp
from .users import users_bp
from .models import models_bp

# 注册所有蓝图
__all__ = ['auth_bp', 'users_bp', 'models_bp']