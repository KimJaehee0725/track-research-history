---
type: idea
title: "Paper Recall식 연구 위키 회수 레이어와 로컬 서버"
date: "2026-07-03 16:52 +0900"
status: open
tags: [history, idea, paper-recall, local-wiki, research-wiki]
---
# Idea 0002 - Paper Recall식 연구 위키 회수 레이어와 로컬 서버

Date: 2026-07-03 16:52 +0900
Status: open
Tags: paper-recall, local-wiki, research-wiki

## Problem / Opportunity

현재 history skill은 agent 작업 기록과 BM25 recall에는 강하지만, 논문을 제목 없이 개념·질문·미팅 맥락으로 다시 찾는 사람용 연구 위키 흐름은 별도 레이어로 정리되어 있지 않다.

## Hypothesis

Git-tracked history/를 source of truth로 유지하면서 paper/concept/question/meeting 노트 타입, 회수 테스트, read-only local wiki server를 추가하면 Paper Recall의 장점을 기존 CLI/BM25/Obsidian-compatible 구조와 충돌 없이 흡수할 수 있다.

## Expected Value

논문 노트는 근거와 다시 볼 이유를 보존하고, 개념·질문 노트는 검색/회수 경로를 만들며, 로컬 서버는 같은 markdown을 위키처럼 탐색하는 사람용 뷰가 된다.

## Links / Evidence

- https://paper-recall-kit.pages.dev/

## Next Check

먼저 wiki bootstrap/add-paper/lint 확장과 read-only history.py serve 설계를 나눈 뒤, 샘플 키트 문구는 재배포하지 않고 자체 템플릿으로 구현한다.
