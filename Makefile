.PHONY: install test demo clean

install:
	pip install -e .

test:
	python3 tests/test_core.py

demo:
	# 用示例数据跑通全流程 (需要 ffmpeg + 视频)
	riding extract ~/Videos/骑行/*.MP4 --detect-dir detect
	riding highlight --video-dir ~/Videos/骑行 --out-dir output --render
	riding plot --detect-dir detect --out-dir charts --edl output/highlight.json

clean:
	rm -rf output/ charts/ detect/ *.egg-info build/ dist/ __pycache__ riding_highlight/__pycache__