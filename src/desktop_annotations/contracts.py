"""Normalized full-display coordinates shared by voice tools and desktop IPC."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Size = Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class Shape(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    x: Unit
    y: Unit
    color: Literal['red', 'yellow', 'cyan', 'green', 'white']


class Ellipse(Shape):
    kind: Literal['ellipse']
    width: Size
    height: Size


class Arrow(Shape):
    kind: Literal['arrow']
    to_x: Unit
    to_y: Unit


class Text(Shape):
    kind: Literal['text']
    text: str = Field(min_length=1, max_length=100)


class AnnotationDrawing(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['replace', 'clear']
    frame_id: str = Field(max_length=80, description='frame_id returned by capture_execution_screen. Empty only when clearing annotations.')
    shapes: list[Annotated[Ellipse | Arrow | Text, Field(discriminator='kind')]] = Field(max_length=12)
    duration_seconds: int = Field(ge=1, le=60)

    @model_validator(mode='after')
    def operation(self):
        if self.action == 'replace' and not self.shapes:
            raise ValueError('Drawing requires at least one shape.')
        if self.action == 'clear' and self.shapes:
            raise ValueError('Clear requires an empty shapes list.')
        return self



def annotation_tool():
    schema = AnnotationDrawing.model_json_schema()
    definitions = schema.pop('$defs', {})

    def inline(value):
        if isinstance(value, dict):
            if '$ref' in value:
                return inline(definitions[value['$ref'].split('/')[-1]])
            return {key: inline(item) for key, item in value.items() if key not in {'discriminator', 'title'}}
        return [inline(item) for item in value] if isinstance(value, list) else value

    return {'type': 'function', 'name': 'annotate_screen',
            'description': '在执行端桌面画圈、箭头或文字。先调用 capture_execution_screen 截图，再使用返回的 frame_id 定位；标注自动准备，无需用户开启。坐标相对整张截图归一化到0到1，不加入窗口原点、网页留白或DPI倍率。ellipse的(x,y)是外接矩形左上角，width/height是归一化宽高，超出部分裁切；arrow从(x,y)指向(to_x,to_y)，text从(x,y)开始。replace替换上一批标注，clear清除且frame_id可为空。截图是静态的，需要查看变化时再次截图。',
            'parameters': inline(schema)}
