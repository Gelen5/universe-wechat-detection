from __future__ import annotations

import uuid
import re
import shutil
from server.providers import call_context

from server import conversation_repository
from server.skills.adapter_support import article_result, model_image, required_text, topics_result, with_provider
from server.skills.tool_result import ArtifactOutput, ToolResult
from server import skill_host, workbench


def create_tools():
    def progress_for(context):
        """把节点内部进度写进 Run 事件流，前端才能显示"卡在哪一步"。"""
        def emit(step, detail=None):
            try:
                context.emit("tool.progress", {"step": step, **(detail or {})})
            except Exception:
                pass
        return emit

    def latest_artifact(context, artifact_type, items=None):
        if items is None:
            reader = getattr(context, 'input_artifacts', None)
            items = reader() if reader else conversation_repository.list_artifacts(context.conversation_id, context.user_id)
        return max((item for item in items if item["type"] == artifact_type),
                   key=lambda item: (item.get("created_at", ""), item.get("version", 0)), default=None)

    def search_topics(args, context):
        session = {}
        topics = with_provider(lambda: workbench._suggestions(
            required_text(args, "topic"), str(args.get("persona") or "深度观察者"), session,
            progress_for(context)))
        research = session.get("topic_research") or {}
        square = session.get("square_hotspots") or {}
        square_items = square.get("items") or []
        evidence = {
            "checked_at": research.get("checked_at"),
            "search_status": research.get("status", "unavailable"),
            "hotspot_status": session.get("hotspot_status", "unavailable"),
            "search_queries": research.get("queries") or [],
            "fetched_pages": research.get("fetched_count", 0),
            "square_hotspot_status": square.get("status", "unavailable"),
            "search_sources": [{
                "provider": '热点广场缓存/' + item.get('platform_zh', item.get('platform', '')),
                "title": item.get('title', ''), "url": item.get('url', ''),
                "published_at": '', "observed_at": item.get('observed_at'),
                "rank": item.get('rank'), "verification": "cached_headline_not_verified",
            } for item in square_items[:10] if item.get('url', '').startswith('https://')] + [{
                "provider": source.get("provider", "search"),
                "title": source.get("title", ""),
                "url": source.get("url", ""),
                "published_at": source.get("published_at", ""),
                "verification": "search_excerpt_only",
            } for source in (research.get("sources") or [])[:20] if source.get("url", "").startswith("https://")],
            "platform_hotspots": [{
                "title": item.get('title', ''), "platforms": [item.get('platform_zh', item.get('platform', ''))],
                "url": item.get('url', ''), "observed_at": item.get('observed_at'), "rank": item.get('rank'),
            } for item in square_items[:10] if item.get('title')] + [{
                "title": item.get("title", ""), "platforms": item.get("sources") or [],
            } for item in (session.get("skill_hotspots") or [])[:10] if item.get("title")],
        }
        return topics_result(topics, evidence)

    def create_outline(args, context):
        title = required_text(args, "title")
        requirements = str(args.get("requirements") or "")
        persona = str(args.get("persona") or "深度观察者")
        progress = progress_for(context)
        progress("generating", {"label": "生成大纲"})
        if skill_host.enabled() and getattr(context, "conversation_id", None):
            # The vendored workflow owns the node contract; the platform only
            # supplies the model. This is what keeps headings from collapsing
            # back into 「判断一/分节二」 labels.
            state = skill_host.for_conversation(
                context.conversation_id, context.user_id,
                brief=f"{title}\n{requirements}".strip(), upto="strategy", persona=persona)
            frame = skill_host.frame_from_state(state)
        else:
            frame = with_provider(lambda: workbench._framework(title, persona, requirements))
        outline = "\n".join(f"{index}. {part}" for index, part in enumerate(frame["outline"], 1))
        progress("generated", {"label": "大纲已生成", "count": len(frame["outline"])})
        return ToolResult({"title": title, "framework": frame}, (
            ArtifactOutput(type="outline", title=title, content=outline,
                           content_json={"framework": frame}),
        ))

    def write_article(args, context):
        title = str(args.get("title") or args.get("topic") or "").strip()
        if not title:
            raise ValueError("title or topic is required")
        persona, requirements = str(args.get("persona") or "深度观察者"), str(args.get("requirements") or "")
        # The tool arguments are model-generated; retain the authoritative
        # user request so explicit prohibitions cannot disappear in routing.
        if context and getattr(context, 'run_id', None):
            run = conversation_repository.get_run(context.run_id, context.user_id)
            trigger = (conversation_repository.get_message(context.conversation_id, context.user_id,
                       run['trigger_message_id']) if run else None) or {}
            user_request = str(trigger.get('content') or '').strip()
            if user_request and user_request not in requirements:
                requirements += '\n用户当次原始要求（优先于工具转述）：\n' + user_request
        progress = progress_for(context)
        if skill_host.enabled() and getattr(context, "conversation_id", None):
            progress("generating", {"label": "生成正文"})
            state = skill_host.for_conversation(
                context.conversation_id, context.user_id,
                brief=f"{title}\n{requirements}".strip(), upto="draft", persona=persona)
            article = state.draft or ""
            if not article.strip():
                raise ValueError("写作节点未返回正文")
            progress("generated", {"label": "正文已生成", "count": len(article)})
            return article_result(state.selected_title or title, article)
        frame = args.get("framework")
        saved_outline = latest_artifact(context, "outline")
        if saved_outline:
            frame = dict((saved_outline.get("content_json") or {}).get("framework") or {})
            edited_lines = [line.strip().split(". ", 1)[-1].strip()
                            for line in (saved_outline.get("content") or "").splitlines()
                            if line.strip()]
            if len(edited_lines) >= 2:
                frame["outline"] = edited_lines
        if not isinstance(frame, dict) or not frame.get("outline"):
            frame = with_provider(lambda: workbench._framework(title, persona, requirements))
        progress = progress_for(context)
        progress("generating", {"label": "生成正文"})
        article = with_provider(lambda: workbench._draft(title, frame, persona, requirements))
        progress("generated", {"label": "正文已生成", "count": len(article)})
        return article_result(title, article)

    def revise_article(args, context):
        article, requirements = required_text(args, "article"), required_text(args, "requirements")
        response = context.model_service.create_response([
            {"role": "system", "content": "你是公众号编辑。严格基于原文执行用户修改要求，保留未要求修改的事实、结构和内容，只输出修改后的完整正文。"},
            {"role": "user", "content": f"修改要求：\n{requirements}\n\n原文：\n{article}"},
        ], timeout=max(60, int(workbench._setting("WECHAT_TEXT_REQUEST_TIMEOUT", "300") or 300)),
           idempotency_key=context.idempotency_key,
           run_id=context.run_id, user_id=context.user_id)
        return article_result(str(args.get("title") or "修订稿"), response.text)

    def review_article(args, context):
        saved_article = latest_artifact(context, "article")
        article = (saved_article or {}).get("content") or required_text(args, "article")
        requirements = str(args.get("requirements") or "").strip()
        if skill_host.enabled() and getattr(context, "conversation_id", None):
            # Review runs as the workflow's own node, which owns the gates and
            # the quality report instead of an anchored string-replacement loop.
            state = skill_host.for_conversation(
                context.conversation_id, context.user_id,
                brief=requirements or str(args.get("title") or "公众号文章"), upto="review")
            reviewed = state.draft or article
            report = dict(state.quality_report or {})
            report.setdefault('gate', 'passed' if not report.get('blocked') else 'needs_review')
            report.setdefault('changed', reviewed != article)
            report.setdefault('summary', '已按 Skill 复核节点完成检查；请人工确认事实与语气。')
            progress_for(context)("generated", {"label": report['summary'], "count": len(reviewed)})
            return ToolResult({"title": str(args.get("title") or state.selected_title or "公众号文章"),
                               "article": reviewed, "review": report}, (
                ArtifactOutput(type="article", title=str(args.get("title") or state.selected_title or "公众号文章"),
                               content=reviewed),
                ArtifactOutput(type="report", title="Skill 复核报告", content_json=report),
            ))
        session = {
            "id": f"{context.run_id}-review-{uuid.uuid4().hex[:12]}",
            "topic": str(args.get("title") or "公众号文章"),
            "article": article,
            "brief": requirements,
            "conversation": [{"role": "user", "content": requirements}],
            "theme": "default",
            "image_plan": {},
            "images": [],
            "skill_runs": [],
        }
        progress = progress_for(context)
        inherited = call_context.current()
        # Retrying the entire review repeats successful calls and discards edits.
        # The provider layer owns the per-request retry policy instead.
        with workbench.provider_overrides(), call_context.bind(
            **{key: inherited.get(key) for key in ('run_id', 'user_id', 'usage_recorder', 'cost_policy', 'idempotency_key')},
            deadline=inherited.get("deadline"), is_cancelled=context.is_cancelled):
            run = conversation_repository.get_run(context.run_id, context.user_id)
            trigger = (conversation_repository.get_message(context.conversation_id, context.user_id,
                        run['trigger_message_id']) if run else None) or {}
            user_text = str(trigger.get('content') or '')
            local_phrases = r'只(?:做|进行|需)?\s*局部|仅(?:做|进行)?\s*局部|保留(?:原有|文章|全文)?结构|不(?:要|需|必)?(?:深度|全文|结构)重构|不(?:要|能|应|许)?(?:改变|调整|改动|改)(?:文章|全文|原有)?结构'
            local_only = any(not re.search(r'(?:不要|不必|无需|别)\s*$', user_text[max(0, match.start()-6):match.start()])
                             for match in re.finditer(local_phrases, user_text))
            try:
                reviewed, report = (workbench._deep_structure_review(article, session, progress=progress)
                                    if not local_only else workbench._review(article, session, progress=progress))
            except workbench.ProviderError as exc:
                if run and run.get('stage') == 'deai':
                    # A standalone review has its own charge; failed review
                    # must follow the normal failure and refund path.
                    raise
                # The article exists and was already paid for. A failed or timed
                # out review must not destroy it: hand back the untouched draft
                # and record why the review is missing.
                progress_for(context)("generated",
                                      {"label": "复核未完成，已保留原稿", "count": len(article)})
                return ToolResult({"title": session["topic"], "article": article, "review": {
                    "gate": "unavailable", "changed": False,
                    "summary": f"复核未完成（{str(exc)[:120]}），已保留原稿，可稍后重新复核。",
                }}, (
                    ArtifactOutput(type="deviation", title="复核未完成", content_json={
                        "review_status": "unavailable", "reason": str(exc)[:300]}),
                ))
        report.setdefault('summary', '复核仍有待办，请查看报告；当前稿已保留' if report.get('gate') != 'passed' else ('已完成局部改稿并通过检查' if report.get('changed') else '已复核，正文未修改；未发现可安全执行的修改，详情见报告'))
        progress_for(context)("generated", {"label": report["summary"], "count": len(reviewed)})
        return ToolResult({"title": session["topic"], "article": reviewed, "review": report}, (
            ArtifactOutput(type="article", title=session["topic"], content=reviewed),
            ArtifactOutput(type="report", title="反 AI 复核报告", content_json=report),
        ))

    def typeset_article(args, context):
        reader = getattr(context, 'input_artifacts', None)
        artifacts = reader() if reader else conversation_repository.list_artifacts(context.conversation_id, context.user_id)
        saved_article = latest_artifact(context, "article", artifacts)
        article = (saved_article or {}).get("content") or required_text(args, "article")
        matching_review = next((item for item in artifacts if item.get('type') == 'report'
                                and item.get('run_id') == (saved_article or {}).get('run_id')
                                and (item.get('content_json') or {}).get('source') in
                                    {'universe-delete-ai-skill', 'structural_rewrite'}), None)
        if matching_review:
            review = matching_review.get('content_json') or {}
            fidelity = review.get('fidelity_gate') or {}
            editorial = review.get('editorial_quality') or {}
            if (review.get('gate') != 'passed'
                    or (fidelity and fidelity.get('status') != 'passed')
                    or editorial.get('outcome') == 'structure_needs_review'
                    or review.get('article_sha256') != workbench.skill_runtime.digest(article)):
                raise workbench.ProviderError('当前正文的复核未通过或版本已变更，请先处理复核问题再排版')
        session = {"id": uuid.uuid4().hex, "topic": str(args.get("title") or "公众号文章"),
                   "article": article,
                   "theme": str(args.get("theme") or "default"), "image_plan": {}, "images": [],
                   "skill_runs": [], "brief": str(args.get("requirements") or ""),
                   "typeset_html": "", "preview_document": ""}
        heading = re.match(r'^\s*#\s+([^\n]+)', article)
        saved_title = (saved_article or {}).get('title')
        if heading:
            session['topic'] = heading.group(1).strip()
        elif saved_title and saved_title not in {'公众号文章', '修订稿', '正文'}:
            session['topic'] = saved_title
        previous = latest_artifact(context, 'html', artifacts)
        previous_meta = (previous or {}).get('content_json') or {}
        session['previous_layout'] = previous_meta.get('article_html', '')[:6000]
        session['previous_layout_hash'] = previous_meta.get('layout_html_hash')
        latest_article = max((item for item in artifacts if item["type"] == "article"
                              and item.get("run_id") != context.run_id),
                             key=lambda item: item["created_at"], default=None)
        image_artifacts = [item for item in artifacts if item["type"] == "image"
                           and item.get("storage_key") and (not latest_article or
                           item["created_at"] >= latest_article["created_at"])]
        image_artifacts.sort(key=lambda item: item["created_at"])
        image_dir = workbench.OUTPUT_DIR / session["id"] / "images"
        for index, item in enumerate(image_artifacts[-8:], 1):
            source = context.storage.local_path(item["storage_key"])
            if source is None:
                raise ValueError("当前存储不支持读取已生成配图，排版未执行")
            image_dir.mkdir(parents=True, exist_ok=True)
            filename = f"image-{index}{source.suffix}"
            shutil.copyfile(source, image_dir / filename)
            caption = str(item.get("title") or "AI 示意图")
            kind = "cover" if "封面" in caption else "body"
            session["images"].append({"kind": kind, "plan_index": index,
                                      "file": filename, "caption": caption})
            session["image_plan"].setdefault("images", []).append(
                {"kind": kind, "caption": caption})
        progress_for(context)("generating", {"label": "生成公众号 HTML"})
        session['_layout_progress'] = progress_for(context)
        html = with_provider(lambda: workbench._typeset(session))
        preview = session.get("preview_document", "") or html
        progress_for(context)("generated", {"label": "排版已完成", "count": len(preview)})
        return ToolResult({"html": html, "preview_document": preview}, (
            ArtifactOutput(type="html", title=session['topic'], content=preview,
                           content_json={'article_html': html, 'layout_variant': session.get('layout_variant'),
                                         'source_article_id': (saved_article or {}).get('id'),
                                         'source_article_version': (saved_article or {}).get('version'),
                                         'source_article_sha256': workbench.skill_runtime.digest(article),
                                         'layout_html_hash': session.get('layout_html_hash'), 'reading_mode': 'publisher-components',
                                         'layout_repair_trace': session.get('layout_repair_trace', []),
                                         'compliance_allowances': session.get('compliance_allowances', {})}),
        ))

    return {"search_topics": search_topics, "create_outline": create_outline,
            "write_article": write_article,
            "revise_article": revise_article, "review_article": review_article,
            "generate_image": model_image, "typeset_article": typeset_article}
