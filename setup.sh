#!/bin/bash

# 文本样式
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # 重置颜色

# 版本比较函数
version_compare() {
    echo "$@" | awk -F. '{ printf("%d%03d%03d%03d\n", $1,$2,$3,$4); }'
}

echo -e "${BOLD}🚀 欢迎使用公司调研助手安装程序！${NC}\n"

# 检查是否安装 uv
echo -e "${BLUE}正在检查 uv（Python 包安装器）……${NC}"
if command -v uv >/dev/null 2>&1; then
    uv_version=$(uv --version | cut -d' ' -f2)
    echo -e "${GREEN}✓ uv $uv_version 可用，将使用 uv 安装依赖${NC}"
    use_uv=true
else
    echo -e "${YELLOW}⚠ 未找到 uv，将使用 pip${NC}"
    use_uv=false
fi

# 检查是否安装 Python 3.11 或更高版本
echo -e "\n${BLUE}正在检查 Python 版本……${NC}"
if command -v python3 >/dev/null 2>&1; then
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [ "$(version_compare "$python_version")" -ge "$(version_compare "3.11")" ]; then
        echo -e "${GREEN}✓ 已安装 Python $python_version${NC}"
    else
        echo "❌ 需要 Python 3.11 或更高版本，当前版本：$python_version"
        echo "请从 https://www.python.org/downloads/ 安装 Python 3.11 或更高版本"
        exit 1
    fi
else
    echo "❌ 未安装 Python 3"
    echo "请从 https://www.python.org/downloads/ 安装 Python 3.11 或更高版本"
    exit 1
fi

# 检查是否安装 Node.js 18 或更高版本
echo -e "\n${BLUE}正在检查 Node.js 版本……${NC}"
if command -v node >/dev/null 2>&1; then
    node_version=$(node -v | cut -d'v' -f2)
    if [ "$(version_compare "$node_version")" -ge "$(version_compare "18.0.0")" ]; then
        echo -e "${GREEN}✓ 已安装 Node.js $node_version${NC}"
    else
        echo "❌ 需要 Node.js 18 或更高版本，当前版本：$node_version"
        echo "请从 https://nodejs.org/ 安装 Node.js 18 或更高版本"
        exit 1
    fi
else
    echo "❌ 未安装 Node.js"
    echo "请从 https://nodejs.org/ 安装 Node.js 18 或更高版本"
    exit 1
fi

# 询问是否创建虚拟环境
if [ "$use_uv" = true ]; then
    echo -e "\n${BLUE}是否使用 uv 创建 Python 虚拟环境？（推荐）[Y/n]${NC}"
else
    echo -e "\n${BLUE}是否创建 Python 虚拟环境？（推荐）[Y/n]${NC}"
fi
read -r use_venv
use_venv=${use_venv:-Y}

if [[ $use_venv =~ ^[Yy]$ ]]; then
    if [ "$use_uv" = true ]; then
        echo -e "\n${BLUE}正在使用 uv 创建 Python 虚拟环境……${NC}"
        uv venv .venv
        source .venv/bin/activate
        echo -e "${GREEN}✓ 已使用 uv 创建并激活虚拟环境${NC}"

        # 使用 uv 安装 Python 依赖
        echo -e "\n${BLUE}正在使用 uv 安装 Python 依赖……${NC}"
        uv pip install -r requirements.txt
        echo -e "${GREEN}✓ Python 依赖安装完成${NC}"
    else
        echo -e "\n${BLUE}正在使用 pip 创建 Python 虚拟环境……${NC}"
        python3 -m venv .venv
        source .venv/bin/activate
        echo -e "${GREEN}✓ 虚拟环境已创建并激活${NC}"

        # 在虚拟环境中安装 Python 依赖
        echo -e "\n${BLUE}正在虚拟环境中安装 Python 依赖……${NC}"
        pip install -r requirements.txt
        echo -e "${GREEN}✓ Python 依赖安装完成${NC}"
    fi
else
    # 询问是否全局安装依赖
    if [ "$use_uv" = true ]; then
        echo -e "\n${BLUE}是否使用 uv 全局安装 Python 依赖？这可能影响其他 Python 项目。[y/N]${NC}"
    else
        echo -e "\n${BLUE}是否全局安装 Python 依赖？这可能影响其他 Python 项目。[y/N]${NC}"
    fi
    read -r install_global
    install_global=${install_global:-N}

    if [[ $install_global =~ ^[Yy]$ ]]; then
        if [ "$use_uv" = true ]; then
            echo -e "\n${BLUE}正在使用 uv 全局安装 Python 依赖……${NC}"
            uv pip install -r requirements.txt --system
            echo -e "${GREEN}✓ Python 依赖安装完成${NC}"
        else
            echo -e "\n${BLUE}正在全局安装 Python 依赖……${NC}"
            pip3 install -r requirements.txt
            echo -e "${GREEN}✓ Python 依赖安装完成${NC}"
        fi
        echo -e "${BLUE}注意：依赖已安装到全局 Python 环境${NC}"
    else
        echo -e "${BLUE}已跳过 Python 依赖安装，稍后需要手工安装。${NC}"
        if [ "$use_uv" = true ]; then
            echo -e "${BLUE}可运行以下命令安装：uv pip install -r requirements.txt${NC}"
        else
            echo -e "${BLUE}可运行以下命令安装：pip install -r requirements.txt${NC}"
        fi
    fi
fi

# 安装 Node.js 依赖
echo -e "\n${BLUE}正在安装 Node.js 依赖……${NC}"
cd ui
npm install
# 创建或覆盖前端开发环境的 .env.development
cat > .env.development << EOL
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
EOL
cd ..
echo -e "${GREEN}✓ Node.js 依赖安装完成${NC}"

# 配置 .env 文件
echo -e "\n${BLUE}正在配置环境变量……${NC}"
if [ -f ".env" ]; then
    echo "发现已有 .env 文件，是否覆盖？(y/n)"
    read -r overwrite
    if [ "$overwrite" != "y" ]; then
        echo "保留现有 .env 文件"
    else
        setup_env=true
    fi
else
    setup_env=true
fi

if [ "$setup_env" = true ]; then
    echo -e "\n请输入 API Key（输入内容不会显示在终端）："
    echo -n "Tavily API Key："
    read -r -s tavily_key
    echo
    if [ -z "$tavily_key" ]; then
        echo "❌ Tavily API Key 不能为空"
        exit 1
    fi

    echo -e "\n请选择一个 LLM 服务商："
    echo "1) OpenCode Zen（DeepSeek V4 Flash，限时免费）"
    echo "2) DeepSeek"
    echo "3) Moonshot（Kimi）"
    echo "4) 阿里百炼（Qwen）"
    echo "5) 智谱 GLM"
    echo "6) MiniMax"
    echo "7) 小米 MiMo"
    echo "8) OpenRouter"
    echo "9) OpenAI"
    read -r llm_choice
    llm_choice=${llm_choice:-1}
    case "$llm_choice" in
        1) llm_key_name="OPENCODE_API_KEY" ;;
        2) llm_key_name="DEEPSEEK_API_KEY" ;;
        3) llm_key_name="MOONSHOT_API_KEY" ;;
        4) llm_key_name="DASHSCOPE_API_KEY" ;;
        5) llm_key_name="ZAI_API_KEY" ;;
        6) llm_key_name="MINIMAX_API_KEY" ;;
        7) llm_key_name="MIMO_API_KEY" ;;
        8) llm_key_name="OPENROUTER_API_KEY" ;;
        9) llm_key_name="OPENAI_API_KEY" ;;
        *)
            echo "❌ LLM 服务商选项无效"
            exit 1
            ;;
    esac
    if [ "$llm_key_name" = "OPENCODE_API_KEY" ]; then
        echo -e "${YELLOW}注意：OpenCode Zen 的免费模型为限时免费，请求会发送到美国，免费期间的数据可能用于模型改进。请勿提交个人、机密或受监管的数据。${NC}"
    fi
    echo -n "${llm_key_name}："
    read -r -s llm_key
    echo
    if [ -z "$llm_key" ]; then
        echo "❌ LLM API Key 不能为空"
        exit 1
    fi

    echo -n "MongoDB URI（可选，按回车跳过）："
    read -r mongodb_uri

    # 创建 .env 文件
    {
        printf 'TAVILY_API_KEY=%s\n' "$tavily_key"
        printf '%s=%s\n' "$llm_key_name" "$llm_key"
    } > .env

    # 提供 MongoDB URI 时写入配置
    if [ -n "$mongodb_uri" ]; then
        printf 'MONGODB_URI=%s\n' "$mongodb_uri" >> .env
    fi

    echo -e "${GREEN}✓ 环境变量已保存到 .env${NC}"
    echo "如需免费模型不可用时自动付费回退，请按 README 在 .env 中再配置一家或多家付费服务商 Key。"
fi

# 显示完成说明和服务启动选项
echo -e "\n${BOLD}🎉 安装完成！${NC}"

if [[ $use_venv =~ ^[Yy]$ ]]; then
    if [ "$use_uv" = true ]; then
        echo -e "\n${BLUE}虚拟环境已激活（由 uv 管理）${NC}"
    else
        echo -e "\n${BLUE}虚拟环境已激活${NC}"
    fi
fi

# 询问是否立即启动服务
echo -e "\n${BLUE}是否立即启动应用服务？[Y/n]${NC}"
read -r start_servers
start_servers=${start_servers:-Y}

if [[ $start_servers =~ ^[Yy]$ ]]; then
    echo -e "\n${BLUE}请选择后端启动方式：${NC}"
    echo "1) python application.py"
    echo "2) uvicorn application:app --reload --port 8000"
    read -r backend_choice

    # 在后台启动后端服务
    if [ "$backend_choice" = "1" ]; then
        echo -e "\n${GREEN}正在使用 Python 启动后端服务……${NC}"
        python application.py &
    else
        echo -e "\n${GREEN}正在使用 Uvicorn 启动后端服务……${NC}"
        uvicorn application:app --reload --port 8000 &
    fi

    # 保存后端进程 ID
    backend_pid=$!

    # 等待后端服务启动
    sleep 2

    # 启动前端服务
    echo -e "\n${GREEN}正在启动前端服务……${NC}"
    cd ui
    npm run dev &
    frontend_pid=$!
    cd ..

    echo -e "\n${GREEN}服务正在启动，应用访问地址：${NC}"
    echo -e "${BOLD}http://localhost:5174${NC}"

    # 注册退出处理，脚本终止时清理服务进程
    trap 'kill $backend_pid $frontend_pid 2>/dev/null' EXIT

    # 保持脚本运行，直到用户主动停止
    echo -e "\n${BLUE}按 Ctrl+C 停止服务${NC}"
    wait
else
    echo -e "\n${BOLD}手工启动应用：${NC}"
    echo -e "\n1. 选择一种方式启动后端服务："
    echo "   方式 1：python application.py"
    echo "   方式 2：uvicorn application:app --reload --port 8000"
    echo -e "\n2. 在新终端中启动前端："
    echo "   cd ui"
    echo "   npm run dev"
    echo -e "\n3. 访问应用：${BOLD}http://localhost:5174${NC}"
fi

echo -e "\n${BOLD}需要帮助？${NC}"
echo "- 文档：README.md"
echo "- 问题反馈：https://github.com/BovmantH/cn-company-research-agent/issues"
echo -e "\n${GREEN}祝调研顺利！🚀${NC}"
