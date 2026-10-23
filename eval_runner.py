
#自动运行学习助手Agent评估用例
import json
from pathlib import Path
from agent_runner import create_messages, run_agent
#获得当前项目目录
BASE_DIR=Path(__file__).resolve().parent
# 拼接评估用例文件的完整路径
EVAL_FILE = BASE_DIR / "eval_cases.json"
#评估结果文件的完整路径
RESULT_FILE=BASE_DIR/"eval_results.json"
#拼接评估用例文件的完整路径
def load_eval_cases():
    """读取评估用例"""
    with EVAL_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    return cases
def check_answer_keywords(answer,expected_keywords):
    """检查最终回答是否包含所有预期关键词,返回是否全部包含，缺少哪些关键词"""
    if answer is None:
        answer = ""
    answer_lower=answer.lower()
    missing_keywords=[]
    for keyword in expected_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower not in answer_lower:
            missing_keywords.append(keyword)
    keyword_pass=len(missing_keywords)==0
    return  keyword_pass,missing_keywords
def evaluate_case(case):
    """执行一条评估用例"""
    #每条测试都创建全新的对话
    messages = create_messages()
    # 将当前测试问题加入对话
    messages.append({
        "role": "user",
        "content": case["question"]
    })
    # 执行Agent，不打印中间工具详情
    agent_result = run_agent(
        messages=messages,
        verbose=False)
# 取得实际工具调用记录
    actual_tools=agent_result["called_tools"]
#取出预期工具
    expected_tools=case["expected_tools"]
#比较实际调用工具和预期工具是否一致
    tool_pass = actual_tools == expected_tools
#检查最终回答
    keyword_pass, missing_keywords = check_answer_keywords(
    answer=agent_result["answer"],#实际回答
    expected_keywords=case["expected_answer_keywords"]#预期关键词
)
    case_pass = tool_pass and keyword_pass#判断整条用例是否通过
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "question": case["question"],
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
        "tool_pass": tool_pass,
        "expected_answer_keywords": case["expected_answer_keywords"],
        "missing_keywords": missing_keywords,
        "keyword_pass": keyword_pass,
        "case_pass": case_pass,
        "steps": agent_result["steps"],
        "answer": agent_result["answer"],
        "tool_trace":agent_result["tool_trace"]
    } #这个函数的目的达到了，测试一条用例返回一个评估报告

def run_evaluation():
    """运行全部评估用例并统计结果"""
    cases = load_eval_cases()
    evaluation_results = []#保存评估结果
    print("开始执行Agent评估")
    print("评估用例数量：", len(cases))
    #依次取出每条用例
    #使用try except异常处理，如果一条出现异常，剩余测试依旧完成
    for index,case in enumerate(cases,start=1):
        print("=" * 60)
        print(f"正在执行第{index}/{len(cases)}条："f"{case['case_id']} - {case['category']}")
        try:#防止一条测试异常中断整个测试集
            result = evaluate_case(case)
        except Exception as error:#如果 evaluate_case(case) 执行过程中发生异常，就把异常保存到变量 error 中。
            result = {#发生异常创建失败结果
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "question": case["question"],
                    "expected_tools": case["expected_tools"],
                    "actual_tools": [],
                    "tool_trace":[],
                    "tool_pass": False,
                    "expected_answer_keywords": (
                        case["expected_answer_keywords"]
                    ),
                    "missing_keywords": (
                        case["expected_answer_keywords"]
                    ),
                    "keyword_pass": False,
                    "case_pass": False,
                    "steps": 0,
                    "answer": "",
                    "error": str(error)
                        }
        evaluation_results.append(result)#无论成功还是失败，都保存当前结果
        print("预期工具：", result["expected_tools"])
        print("实际工具：", result["actual_tools"])
        print("工具轨迹：")

        for trace_item in result["tool_trace"]:
            print("  工具名称：", trace_item["tool_name"])
            print("  执行状态：", trace_item["status"])
            print("  执行耗时：", trace_item["duration_ms"], "毫秒")

            if trace_item["error"] is not None:
                print("  错误原因：", trace_item["error"])
        if result["tool_pass"]:
            print("工具检查：通过")
        else:
            print("工具检查：失败")
    #所有用例执行结束后，开始统计总成绩
    total_cases = len(evaluation_results)

    tool_pass_count = 0#调用正确的工具以及调用工具顺序正确的用例数量
    keyword_pass_count = 0#有多少条用例的最终回答包含了全部预期关键词
    case_pass_count = 0#整体通过的用例数量

    # 依次检查每一条评估结果
    for evaluation_result in evaluation_results:
        if evaluation_result["tool_pass"]:
            tool_pass_count += 1

        if evaluation_result["keyword_pass"]:
            keyword_pass_count += 1

        if evaluation_result["case_pass"]:
            case_pass_count += 1

    # 计算整体通过率
    if total_cases == 0:
        overall_pass_rate = 0
    else:
        overall_pass_rate = case_pass_count / total_cases

    # 保存汇总结果
    summary = {
        "total_cases": total_cases,
        "tool_pass_count": tool_pass_count,
        "keyword_pass_count": keyword_pass_count,
        "case_pass_count": case_pass_count,
        "overall_pass_rate": overall_pass_rate
    }

    # 完整结果由“汇总”和“每条详细结果”组成
    output = {
        "summary": summary,
        "results": evaluation_results
    }

    # 将评估结果写入JSON文件
    with RESULT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print("=" * 60)
    print("评估完成")
    print(f"工具检查通过：{tool_pass_count}/{total_cases}")
    print(f"关键词检查通过：{keyword_pass_count}/{total_cases}")
    print(f"整体通过：{case_pass_count}/{total_cases}")
    print(f"整体通过率：{overall_pass_rate:.2%}")
    print("详细结果已保存到：", RESULT_FILE)
if __name__ == "__main__":
    run_evaluation()
    






