from fastapi.testclient import TestClient

from server.main import app


def test_public_seo_files_are_crawlable():
    client = TestClient(app)
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap: https://yuzoudiyigongzuotai.cn/sitemap.xml" in robots.text
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    verification = client.get("/baidu_verify_codeva-g1x7XWVb4z.html")
    assert verification.status_code == 200
    assert verification.text == "d86ba9182344b4887ee9d491775ab709"
    for path in ("/ai-writing", "/wechat-official-account", "/sticker-account", "/ai-skills"):
        page = client.get(path)
        assert page.status_code == 200
        assert '<link rel="canonical" href="https://yuzoudiyigongzuotai.cn' in page.text
        assert 'application/ld+json' in page.text


def test_root_has_a_descriptive_search_title():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "公众号 AI 写作、贴图号与创作者 Skill 工作台" in response.text
