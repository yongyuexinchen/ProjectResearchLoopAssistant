import test from "node:test";
import assert from "node:assert/strict";
import { readSourceIndex, filterSourceFunctions, sourceLineLabel } from "../lib/source-navigation.ts";

const fn = { id:"a", path:"api/chat.py", name:"chat", qualified_name:"chat", line_start:4, line_end:12,
  parameters:["payload"], docstring:"接收消息", statements:[{kind:"return",label:"返回结果",line_start:12,line_end:12,excerpt:"return result"}],
  calls:[{expression:"engine.process",line:8,column:4,target_id:null,resolution:"unresolved",reason:"动态接收者"}],entrypoint:null };

test("source search follows paths, docstrings and exact call expressions", () => {
  for (const query of ["CHAT.PY", "接收消息", "engine.process", "返回结果"]) {
    assert.equal(filterSourceFunctions([fn], query)[0].id, "a");
  }
  assert.deepEqual(filterSourceFunctions([fn], "missing"), []);
  assert.equal(sourceLineLabel(4,12), "L4–L12");
});

test("source index must have a supported version and correct ranges", () => {
  const value = {version:1,functions:[fn],files:[],stats:{},limits:{},warnings:[]};
  assert.equal(readSourceIndex(value)?.functions[0].id,"a");
  for (const invalid of [null, {}, {...value,version:2}, {...value,functions:[{...fn,line_end:1}]},
      {...value,functions:[{...fn,calls:[null]}]}, {...value,functions:[{...fn,statements:[null]}]},
      {...value,functions:[{...fn,calls:[{...fn.calls[0],reason:{}}]}]},
      {...value,functions:[{...fn,calls:[{...fn.calls[0],column:-1}]}]},
      {...value,functions:[{...fn,entrypoint:{label:"入口",line:"3"}}]}]) {
    assert.equal(readSourceIndex(invalid),null);
  }
});
