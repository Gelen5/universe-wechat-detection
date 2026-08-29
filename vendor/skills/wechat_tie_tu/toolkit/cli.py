#!/usr/bin/env python3
"""Command-line interface for the independent WeChat Tie-Tu workflow."""
from __future__ import annotations
import argparse, json, os, sys

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tie-tu", description="独立的微信贴图号内容工作流")
    sub = p.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="生成贴图号卡片策划")
    plan.add_argument("--industry", required=True); plan.add_argument("--topic", required=True)
    plan.add_argument("--title"); plan.add_argument("--content-type", choices=["tutorial", "before_after", "list", "industry_view", "city_change", "emotional_story"])
    plan.add_argument("--count", type=int, default=5); plan.add_argument("--style"); plan.add_argument("--audience")
    plan.add_argument("--portrait-mode", choices=["auto", "required", "off"], default="auto"); plan.add_argument("--output", default="card_plan.json"); plan.add_argument("--recommend", action="store_true")
    preview = sub.add_parser("preview", help="生成手机预览 HTML"); preview.add_argument("plan"); preview.add_argument("--output", "-o")
    validate = sub.add_parser("validate", help="检查策划与图片"); validate.add_argument("plan")
    status = sub.add_parser("status", help="查看状态"); status.add_argument("plan")
    approve = sub.add_parser("approve", help="更新审批状态"); approve.add_argument("plan"); approve.add_argument("--stage", required=True, choices=["topic", "brief", "card_plan", "pilot_image", "batch_generation", "preview", "publish"]); approve.add_argument("--status", required=True, choices=["pending", "approved", "rejected", "blocked"]); approve.add_argument("--note")
    source = sub.add_parser("source", help="记录来源"); source.add_argument("plan"); source.add_argument("--source-id", required=True); source.add_argument("--kind", required=True, choices=["web", "user", "ai", "reference", "claim"]); source.add_argument("--title"); source.add_argument("--url"); source.add_argument("--evidence"); source.add_argument("--status", choices=["verified", "illustrative", "unverified", "rejected"], default="unverified"); source.add_argument("--license")
    prompt = sub.add_parser("portrait-prompt", help="输出人像增强提示词"); prompt.add_argument("plan"); prompt.add_argument("--index", type=int)
    pilot = sub.add_parser("pilot", help="记录宿主内置 Image 已生成的图片"); pilot.add_argument("plan"); pilot.add_argument("--index", type=int, default=1); pilot.add_argument("--image")
    batch = sub.add_parser("batch", help="检查宿主内置 Image 生成结果是否已全部记录"); batch.add_argument("plan")
    reverse = sub.add_parser("reverse-image", help="分析参考图"); reverse.add_argument("plan"); reverse.add_argument("--image", required=True)
    publish = sub.add_parser("publish", help="发布到微信草稿箱"); publish.add_argument("plan")
    args = p.parse_args(argv)
    from .tie_tu import (TieTuPublisher, add_source, attach_reference_analysis, build_plan, generate_batch, load_plan, record_pilot, recommend_types, render_portrait_prompt, render_preview, save_plan, set_approval, validate_plan)
    if args.command == "plan":
        if args.recommend:
            print(json.dumps(recommend_types(args.industry, args.topic, args.title or ""), ensure_ascii=False, indent=2)); return 0
        save_plan(build_plan(args.industry, args.topic, args.title or "", args.content_type, args.count, args.style or "", args.audience or "", args.portrait_mode), args.output); print(f"贴图号 card_plan 已生成: {args.output}"); return 0
    if args.command == "preview":
        out = args.output or os.path.splitext(args.plan)[0] + "_preview.html"; render_preview(load_plan(args.plan), out); print(f"贴图号预览已生成: {out}"); return 0
    if args.command == "validate":
        report = validate_plan(load_plan(args.plan)); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["ok"] else 1
    if args.command == "status":
        plan = load_plan(args.plan); print(json.dumps({"approval": plan.approval_state.stages, "generation": plan.generation_state.__dict__, "quality_gate": plan.quality_gate.__dict__}, ensure_ascii=False, indent=2)); return 0
    if args.command == "approve":
        plan = load_plan(args.plan); set_approval(plan, args.stage, args.status, args.note or ""); save_plan(plan, args.plan); print(f"贴图号审批状态已更新: {args.stage}={args.status}"); return 0
    if args.command == "source":
        plan = load_plan(args.plan); add_source(plan, args.source_id, args.kind, args.title or "", args.url or "", args.evidence or "", args.status, args.license or ""); save_plan(plan, args.plan); print(f"贴图号来源已记录: {args.source_id}"); return 0
    if args.command == "portrait-prompt":
        plan = load_plan(args.plan)
        if not plan.portrait_enabled: print("该计划未启用人像增强，请重新生成计划。", file=sys.stderr); return 1
        cards = [c for c in plan.cards if not args.index or c.index == args.index]
        for card in cards: print(f"--- card {card.index} / {card.role} ---\n{render_portrait_prompt(card.portrait_spec)}\nNEGATIVE: {card.portrait_spec['negative_prompt']}")
        return 0
    if args.command == "pilot":
        plan = load_plan(args.plan)
        if not args.image:
            print("pilot 只记录当前宿主内置 Image 已生成的图片。请先调用宿主生图，再传入 --image；本 Skill 不需要 API Key，也不提供 CLI/API 生图回退。", file=sys.stderr)
            return 2
        record_pilot(plan, args.index, args.image, "generated")
        save_plan(plan, args.plan); return 0
    if args.command == "batch":
        plan = load_plan(args.plan); count = generate_batch(plan, ""); save_plan(plan, args.plan); print(f"贴图号图片已记录: {count}/{len(plan.cards)}")
        if count != len(plan.cards):
            print("请继续使用当前宿主内置 Image 逐张生成，并用 pilot --index N --image 记录；不要配置图片 API Key。", file=sys.stderr)
            return 1
        return 0
    if args.command == "reverse-image":
        plan = load_plan(args.plan); result = attach_reference_analysis(plan, args.image); save_plan(plan, args.plan); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    if args.command == "publish":
        media_id = TieTuPublisher().publish_draft(load_plan(args.plan)); print(f"贴图号草稿已创建: media_id={media_id}" if media_id else "贴图号草稿创建失败"); return 0 if media_id else 1
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
