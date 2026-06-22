# -*- coding: utf-8 -*-
"""TiTS JS 扫描规则（旧版，现已被 scanner.py 内置逻辑取代）"""

# 注意：当前 scanner.py 使用内置的 CALL_EXTRACTORS / ARG_EXTRACTORS / ASSIGN_PATTERNS
# 本文件保留作为参考，未来可扩展为外部规则注册表

import re
from util import semantic_key, format_pos, context_hash

RULES = []
