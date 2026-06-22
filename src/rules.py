# -*- coding: utf-8 -*-
"""TiTS JS 扫描规则注册表

scanner.py 从这里加载所有提取规则。
新增规则只需要在这里注册，不用动 scanner。

规则类型：
  - call:    遇到 func( 时，整体提取括号内容（如 output/combatAppend）
  - arg:     遇到 func( 时，提取第N个参数的字符串（如 addButton/showName）
  - assign:  遇到 pattern = "..." 时，提取字符串（如 this.short）
  - field:   遇到 field:"..." 时，提取字符串（如 text/ttB/dttB）
  - custom:  自定义处理函数（如 textify 的 tagged template）
"""


# ================================================================
#   规则存储
# ================================================================

# name -> category
CALL_RULES = {}

# name -> (arg_index, category)
ARG_RULES = {}

# pattern_string -> category
ASSIGN_RULES = {}

# field_name -> category
FIELD_RULES = {}

# name -> handler(scanner, name_end) -> None
CUSTOM_RULES = {}


# ================================================================
#   注册 API
# ================================================================

def register_call(name, category):
    """注册完整调用提取规则：遇到 name( 时提取整个括号内容"""
    CALL_RULES[name] = category


def register_arg(name, arg_index, category):
    """注册参数提取规则：遇到 name( 时提取第 arg_index 个参数"""
    ARG_RULES[name] = (arg_index, category)


def register_assign(pattern, category):
    """注册赋值模式规则：遇到 pattern = \"...\" 时提取字符串"""
    ASSIGN_RULES[pattern] = category


def register_field(field, category):
    """注册对象字段规则：遇到 field:\"...\" 时提取字符串"""
    FIELD_RULES[field] = category


def register_custom(name, handler):
    """注册自定义处理规则：遇到 name( 时调用 handler(scanner, name_end)"""
    CUSTOM_RULES[name] = handler


# ================================================================
#   默认规则注册
# ================================================================

# --- 完整调用提取 ---
register_call('output',       'output')
register_call('outputText',   'output')
register_call('combatAppend', 'combat')

# --- 参数提取 ---
register_arg('addButton',         1, 'button')
register_arg('addDisabledButton', 1, 'button')
register_arg('showName',          0, 'name.show')
register_arg('showBust',          0, 'bust')
register_arg('createPerk',        0, 'perk')
register_arg('author',            0, '_skip')

# --- 赋值模式 ---
register_assign('this.short',        'name.short')
register_assign('this.long',         'desc.long')
register_assign('this.description',  'desc')
register_assign('this.ButtonName',   'ui.button')
register_assign('this.TooltipTitle', 'ui.tooltip')

# --- 对象字段 ---
register_field('text', 'button.text')
register_field('ttB',  'button.ttB')
register_field('dttB', 'button.dttB')
