# Flask 基础请求处理

## 课程背景

本节面向高职或大专学生。学生已经学过 Python 变量、条件判断、函数和字典，
但还没有被要求掌握复杂的前后端分离。上课使用 Windows、VS Code、Python、
Flask 和桌面浏览器。理论课按 120 分钟准备，随后安排 120 分钟机房实践。

## 本节范围

本节围绕一个很小的“课程查询”网页理解浏览器与服务器如何协作，涉及：

- HTTP request 与 response 的基本概念，以及请求方法、状态码、请求参数和响应内容；
- Flask 应用、路由和视图函数；
- 路径参数与查询参数的区别和读取方式；
- 表单提交，GET 与 POST 的基本使用场景；
- `render_template` 把数据交给 HTML 模板；
- 基本输入校验和清晰的错误响应；
- 在浏览器中观察 URL、页面结果和错误情况。

本节不展开复杂的前后端分离、数据库 ORM、异步接口、身份认证或部署。

## 概念说明

浏览器发出 request 时，至少要有目标 URL 和请求方法；服务器处理后返回 response。
response 中的状态码表达处理结果，响应正文才是页面或数据本身。开发时可以同时
观察地址栏、页面文字和开发者工具中的 Network 信息，但课堂示例以浏览器可见结果
为主。

Flask 用路由规则把 URL 映射到 Python 函数。路径中的动态片段属于资源定位的一部分，
查询字符串更适合表达筛选条件；两者都不是“把所有输入直接当成可信数据”。

表单把用户输入交给服务器。读取表单前要考虑请求方法，读取之后要做存在性、类型和
范围等基本检查，再决定返回成功结果还是可理解的错误提示。

模板的作用是把视图函数准备的数据放进 HTML 页面。视图函数负责请求处理和准备数据，
模板负责展示；即使示例很小，也应保持这两个责任边界清楚。

## 课堂代码素材

下面是课堂上用于说明路由、参数和模板的片段。它们是教学素材，不是已经拆好的
学生任务或实践答案。

### 最小应用与路径参数

```python
from flask import Flask, request, render_template

app = Flask(__name__)

@app.get("/course/<int:course_id>")
def course_detail(course_id):
    return {"course_id": course_id, "message": "course lookup"}
```

### 查询参数与基本校验

```python
@app.get("/search")
def search():
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return {"error": "keyword is required"}, 400
    return {"keyword": keyword, "items": ["Flask", "HTTP"]}
```

### 表单和模板

```python
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return render_template("register.html", error="请输入姓名"), 400
        return render_template("register.html", message=f"欢迎，{name}")
    return render_template("register.html")
```

模板可以读取视图传入的变量：

```html
{% if error %}<p class="error">{{ error }}</p>{% endif %}
{% if message %}<p>{{ message }}</p>{% endif %}
<form method="post">
  <label>姓名 <input name="name"></label>
  <button type="submit">登记</button>
</form>
```

## 浏览器观察素材

打开一个 GET 地址时，地址栏能看到路径和查询字符串；提交表单时，要观察页面是否
给出成功或错误结果，以及服务器是否针对请求方法返回了预期响应。输入空字符串、
只含空格、整数路径和不存在的路径，适合用来讨论“校验发生在哪里”和“错误信息是否
能帮助使用者修正输入”。

课堂结束时，学生应能用自己的话说明一次请求从浏览器到 Flask 视图再到响应页面的
基本经过，并能根据可观察结果定位参数读取或输入校验中的明显问题。
