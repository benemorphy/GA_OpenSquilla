model:qwen3.5-35b
api:https://ai.upcloud.unionpay.com/v1/chat/completions
api_key:b9716c4a-2a1c-4965-93c5-d2b0ec80a1f2



对话服务接口示例：
python 
import requests 
headers = {"Authorization": "Bearer API_KEY"} #API_KEY 请替换为实际分配的
data = { "model": "deepseek-r1:32b", "messages": [{"role":"user","content":"你好"}] } 
response = requests.post("https://api.yourdomain.com/v1/chat/completions", json=data, headers=headers)