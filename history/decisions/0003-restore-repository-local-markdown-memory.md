---
type: decision
title: "Restore repository-local Markdown memory"
date: "2026-08-03 05:08 +0000"
status: accepted
tags: [history, decision]
---
# Decision 0003 - Restore repository-local Markdown memory

Date: 2026-08-03 05:08 +0000
Status: accepted

## Context

중앙 SSH/password memory service와 서버-side index가 각 프로젝트의 단순한 Markdown history보다 운영 부담과 결합도를 크게 만들었다. 사용자는 BM25S만 유지하고 SQLite를 사용하지 않기를 명시했다.

## Decision

각 프로젝트 repo의 history/ Markdown과 Git을 유일한 durable source로 사용한다. 검색은 vendored BM25S와 NumPy만 사용하고, PROJECT_MAP.md의 상대 wikilink로 Obsidian graph 탐색을 제공한다.

## Rationale

별도 서비스·credential·database·migration 없이 clone된 프로젝트만으로 recall과 기록이 동작하며, Obsidian도 같은 파일을 직접 읽을 수 있다.

## Consequences

중앙 server/client/deploy/password/SSH 구성은 제거한다. 기존 중앙화 결정은 superseded 상태로 보존하고, 프로젝트별 history/를 Obsidian vault로 연다.
