"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None
    # 幂等令牌回显与重复标记：重复请求拿到同样的最终结果，界面据此确认状态而非再执行一次。
    token: str | None = None
    duplicate: bool = False


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。

    动作接口同时兼容两种历史协议：
    - 新协议：动作放在顶层 ``action``，幂等令牌放在顶层 ``token``；
    - 旧协议：动作嵌在 ``values.action`` 里。
    两处都给动作且取值不一致时按冲突拒绝，由路由层统一判定。
    """

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None
    action: str | None = None
    token: str | None = None



class CollectorEntry(BaseModel):
    """采集任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 目标网址
    field_2: str | None = None  # HTTP方法
    field_3: str | None = None  # 请求头部
    field_4: str | None = None  # 并发线程
    field_5: str | None = None  # 超时秒数
    field_6: str | None = None  # 代理地址
    field_7: str | None = None  # 字符编码

class CrawlruleEntry(BaseModel):
    """抽取规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 入口地址
    field_2: str | None = None  # 列表选择器
    field_3: str | None = None  # 详情链接选择器
    field_4: str | None = None  # 正文选择器
    field_5: str | None = None  # 下一页选择器
    field_6: str | None = None  # 分页参数
    field_7: str | None = None  # 请求间隔

class ParserEntry(BaseModel):
    """解析模板明细结构。"""

    field_0: str | None = None  # 模板编号
    field_1: str | None = None  # 目标字段名
    field_2: str | None = None  # XPath表达式
    field_3: str | None = None  # 正则模式
    field_4: str | None = None  # 默认取值
    field_5: str | None = None  # 字段类型
    field_6: str | None = None  # 必填标识
    field_7: str | None = None  # 清洗函数

class IncrementEntry(BaseModel):
    """增量游标明细结构。"""

    field_0: str | None = None  # 游标编号
    field_1: str | None = None  # 来源标识
    field_2: str | None = None  # 增量字段
    field_3: str | None = None  # 游标位置
    field_4: str | None = None  # 批次大小
    field_5: str | None = None  # 采集间隔
    field_6: str | None = None  # 起始水位
    field_7: str | None = None  # 截止水位

class RatelimitEntry(BaseModel):
    """限速策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 目标域名
    field_2: str | None = None  # 并发上限
    field_3: str | None = None  # 请求间隔
    field_4: str | None = None  # 每日配额
    field_5: str | None = None  # 令牌桶容量
    field_6: str | None = None  # 填充速率
    field_7: str | None = None  # 超限动作

class RetryEntry(BaseModel):
    """重试策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 失败类型
    field_2: str | None = None  # 最大重试次数
    field_3: str | None = None  # 退避算法
    field_4: str | None = None  # 初始等待秒数
    field_5: str | None = None  # 最大等待秒数
    field_6: str | None = None  # 可重试状态码
    field_7: str | None = None  # 通知渠道

class RpaflowEntry(BaseModel):
    """流程编排明细结构。"""

    field_0: str | None = None  # 流程编号
    field_1: str | None = None  # 入口URL
    field_2: str | None = None  # 页面定位器
    field_3: str | None = None  # 等待条件
    field_4: str | None = None  # 动作步骤序列
    field_5: str | None = None  # 输出映射字段
    field_6: str | None = None  # 超时秒数
    field_7: str | None = None  # 执行批次

class CaptchaEntry(BaseModel):
    """识别方案明细结构。"""

    field_0: str | None = None  # 方案编号
    field_1: str | None = None  # 验证码类型
    field_2: str | None = None  # 识别服务地址
    field_3: str | None = None  # 图片预处理
    field_4: str | None = None  # 字符长度范围
    field_5: str | None = None  # 识别超时秒数
    field_6: str | None = None  # 重试次数
    field_7: str | None = None  # 成功率阈值

class ProxyEntry(BaseModel):
    """代理节点明细结构。"""

    field_0: str | None = None  # 节点编号
    field_1: str | None = None  # 代理地址
    field_2: str | None = None  # 代理协议
    field_3: str | None = None  # 所在区域
    field_4: str | None = None  # 匿名等级
    field_5: str | None = None  # 响应延迟毫秒
    field_6: str | None = None  # 可用率阈值
    field_7: str | None = None  # 每日上限

class SessionEntry(BaseModel):
    """会话配置明细结构。"""

    field_0: str | None = None  # 配置编号
    field_1: str | None = None  # 登录网址
    field_2: str | None = None  # Cookie策略
    field_3: str | None = None  # 会话超时分钟
    field_4: str | None = None  # UserAgent模板
    field_5: str | None = None  # 参照页设置
    field_6: str | None = None  # 保持心跳间隔
    field_7: str | None = None  # 重登触发器

class RouterEntry(BaseModel):
    """分发规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 来源URL模式
    field_2: str | None = None  # 目标引擎
    field_3: str | None = None  # 优先级权重
    field_4: str | None = None  # 分发比例
    field_5: str | None = None  # 熔断阈值
    field_6: str | None = None  # 降级策略
    field_7: str | None = None  # 健康检查间隔

class ValidateEntry(BaseModel):
    """校验规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 校验目标字段
    field_2: str | None = None  # 校验表达式
    field_3: str | None = None  # 期望取值
    field_4: str | None = None  # 容差范围
    field_5: str | None = None  # 采样比例
    field_6: str | None = None  # 阻断级别
    field_7: str | None = None  # 告警触发

class DedupEntry(BaseModel):
    """去重策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 业务键列
    field_2: str | None = None  # 相似度算法
    field_3: str | None = None  # 去重阈值
    field_4: str | None = None  # 时间窗口天数
    field_5: str | None = None  # 保留策略
    field_6: str | None = None  # 布隆过滤容量
    field_7: str | None = None  # 索引字段

class FormatEntry(BaseModel):
    """转换规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 输入字段
    field_2: str | None = None  # 输出字段
    field_3: str | None = None  # 转换函数
    field_4: str | None = None  # 默认取值
    field_5: str | None = None  # 异常策略
    field_6: str | None = None  # 格式化模板
    field_7: str | None = None  # 校验正则

class PipelineEntry(BaseModel):
    """流水线编排明细结构。"""

    field_0: str | None = None  # 流水线编号
    field_1: str | None = None  # 阶段顺序
    field_2: str | None = None  # 阶段名称
    field_3: str | None = None  # 处理引擎
    field_4: str | None = None  # 上游阶段
    field_5: str | None = None  # 超时分钟
    field_6: str | None = None  # 失败策略
    field_7: str | None = None  # 输出数据集

class StorageEntry(BaseModel):
    """存储配置明细结构。"""

    field_0: str | None = None  # 配置编号
    field_1: str | None = None  # 存储类型
    field_2: str | None = None  # 连接地址
    field_3: str | None = None  # 输出路径
    field_4: str | None = None  # 分区格式
    field_5: str | None = None  # 压缩算法
    field_6: str | None = None  # 保留天数
    field_7: str | None = None  # 冷热策略

class MonitorEntry(BaseModel):
    """监控指标明细结构。"""

    field_0: str | None = None  # 指标编号
    field_1: str | None = None  # 监控目标
    field_2: str | None = None  # 采集频率
    field_3: str | None = None  # 成功率阈值
    field_4: str | None = None  # 延迟阀值毫秒
    field_5: str | None = None  # 告警级别
    field_6: str | None = None  # 通知渠道
    field_7: str | None = None  # 聚合窗口秒数

class SchedulerEntry(BaseModel):
    """调度计划明细结构。"""

    field_0: str | None = None  # 计划编号
    field_1: str | None = None  # Cron表达式
    field_2: str | None = None  # 关联任务
    field_3: str | None = None  # 时区设置
    field_4: str | None = None  # 最大执行时长
    field_5: str | None = None  # 并发上限
    field_6: str | None = None  # 错过补偿策略
    field_7: str | None = None  # 有效日期范围
