import sys
import json
import typing as t

import more_itertools as mit

from datastructures import parse, FileIdentifiers, Task
from dummy import DummyWriter


documents: t.Dict[str, t.Union[str, t.List[str]]] = {}
last_tasks: t.Dict[str, t.List[Task]] = {}


def read_msg() -> t.Optional[t.Dict[str, t.Any]]:
    # Read message's content length and body (as per LSP spec)
    line = sys.stdin.readline()
    if line.startswith("Content-Length:"):
        length = int(line.split(":")[1].strip())
        sys.stdin.readline()  # skip empty line
        body = sys.stdin.read(length)
        return t.cast(
            t.Dict[str, t.Any],
            json.loads(body),
        )
    return None


def send_msg(msg: t.Any) -> None:
    body = json.dumps(msg)
    sys.stdout.write(f"Content-Length: {len(body)}\r\n\r\n{body}")
    sys.stdout.flush()


def make_completion_item(matched_text: str, task: Task, line: int, start_char: int, end_char: int) -> t.Any:
    show_text = f"{task.state} {task.title} ({task.identifier})"
    return {
        "filterText": matched_text,
        "label": show_text,
        "detail": show_text,
        "kind": 23,
        "documentation": "\n".join(task.description),
        "textEdit": {
            "range": {
                "start": {"line": line, "character": start_char},
                "end": {"line": line, "character": end_char},
            },
            "newText": task.identifier or "WTF",
        },
    }


def get_document(uri: str) -> t.Tuple[t.Optional[t.List[str]], t.List[Task]]:
    global documents
    global last_tasks
    document = documents.get(uri)
    if document is None:
        return None, []
    if isinstance(document, str):
        splitted = document.split("\n")
        documents[uri] = splitted
        parsed = parse(
            mit.peekable(enumerate(document.split("\n"))),
            FileIdentifiers("", "", ""),
        )
        if parsed is not None:
            tasks = list(parsed.tasks.values())
            if len(tasks) > 0:
                last_tasks[uri] = tasks
        else:
            tasks = []
        return splitted, tasks
    return t.cast(document, t.List[str]), last_tasks.get(uri, [])


def handle_completion(f: t.TextIO, params: t.Any) -> t.Any:
    line: int = params["position"]["line"]
    character: int = params["position"]["character"]
    document_uri = params["textDocument"]["uri"]
    document, tasks = get_document(document_uri)
    if document is None or line > len(document) or len(tasks) == 0:
        return {"isIncomplete": False, "items": []}
    line_til_char = document[line][:character]
    if "@" not in line_til_char:
        return {"isIncomplete": False, "items": []}
    _, to_suggest = line_til_char.rsplit("@", maxsplit=1)
    tsl = to_suggest.lower()
    relevant_tasks = [
        task
        for task in tasks
        if tsl in task.title.lower() and task.identifier is not None and task.state != "[x]"
    ]
    items = [
        make_completion_item(
            to_suggest,
            task,
            line,
            character - len(to_suggest),
            character,
        )
        for task in relevant_tasks
    ]
    return {"isIncomplete": True, "items": items}


def handle_did_open(params: t.Any) -> None:
    global documents
    text_doc = params["textDocument"]
    uri = text_doc["uri"]
    text = text_doc["text"]
    documents[uri] = text


def handle_did_change(params: t.Any) -> None:
    global documents
    # For simplicity, handle full text synchronization only
    uri = params["textDocument"]["uri"]
    content_changes = params["contentChanges"]
    if content_changes:
        # Taking the full text from the first change only
        documents[uri] = content_changes[0].get("text", documents.get(uri, ""))


def lsp_loop() -> None:
    # with open("log.jsonl", "a") as f:
    with DummyWriter() as f:
        print("start", file=f)
        while True:
            request = read_msg()
            if not request:
                continue
            method = request.get("method")
            if method == "textDocument/didOpen":
                print(method, file=f)
                f.flush()
                handle_did_open(request["params"])
            elif method == "textDocument/didChange":
                print(method, file=f)
                f.flush()
                handle_did_change(request["params"])
            else:
                print(json.dumps(request, indent=2), file=f)
                f.flush()
                if method == "initialize":
                    send_msg(
                        {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "result": {
                                "capabilities": {
                                    "textDocumentSync": {
                                        "openClose": True,
                                        "change": 1,  # 1 = Full text sync (use 2 for incremental if supported)
                                    },
                                    "completionProvider": {"resolveProvider": False},
                                },
                            },
                        }
                    )
                elif method == "textDocument/completion":
                    result = handle_completion(f, request.get("params", {}))
                    print(json.dumps(result, indent=2), file=f)
                    send_msg({"jsonrpc": "2.0", "id": request["id"], "result": result})
                elif method == "shutdown":
                    send_msg({"jsonrpc": "2.0", "id": request["id"], "result": None})
                    break
                elif method == "exit":
                    sys.exit(0)
                else:
                    if "id" in request:
                        send_msg({"jsonrpc": "2.0", "id": request["id"], "result": None})


if __name__ == "__main__":
    lsp_loop()
