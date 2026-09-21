from server import diagnosis_service
from server.skills.adapter_support import report_result, required_text


def create_tools():
    def diagnose(args, context):
        report = diagnosis_service.run(required_text(args, "account_name"), lambda value: value)
        return report_result("公众号诊断报告", report)
    return {"diagnose_account": diagnose}

