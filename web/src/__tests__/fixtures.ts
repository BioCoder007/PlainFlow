import type { RepoModel } from '../types'

export const SOURCE = [
  'import util', //            1
  '', //                       2
  'def total(xs):', //         3
  '    t = 0', //              4
  '    for x in xs:', //       5
  '        if x < 0:', //      6
  '            continue', //   7
  '        t += util.fix(x)', // 8
  '    return fmt(t)', //      9
  '', //                       10
  'def fmt(n):', //            11
  '    return str(n)', //      12
].join('\n')

export const MODEL: RepoModel = {
  files: [
    {
      path: 'app.py',
      line_count: 12,
      parse_error: null,
      imports: [{ module: 'util', line: 1, target: 'pkg/util.py', names: { util: '' } }],
      functions: [
        {
          id: 'app.py::total',
          name: 'total',
          qualname: 'total',
          line_start: 3,
          line_end: 9,
          steps: [
            { id: 's1', kind: 'block', label: 't = 0', line_start: 4, line_end: 4 },
            { id: 's2', kind: 'loop', label: 'for x in xs:', line_start: 5, line_end: 8 },
            { id: 's3', kind: 'branch', label: 'if x < 0:', line_start: 6, line_end: 6 },
            { id: 's4', kind: 'block', label: 'continue', line_start: 7, line_end: 7 },
            { id: 's5', kind: 'block', label: 't += util.fix(x)', line_start: 8, line_end: 8 },
            { id: 's6', kind: 'return', label: 'return fmt(t)', line_start: 9, line_end: 9 },
          ],
          edges: [
            { source: 's1', target: 's2', label: null },
            { source: 's2', target: 's3', label: 'loop' },
            { source: 's3', target: 's4', label: 'true' },
            { source: 's3', target: 's5', label: 'false' },
            { source: 's4', target: 's2', label: null },
            { source: 's5', target: 's2', label: null },
            { source: 's2', target: 's6', label: 'exit' },
          ],
          calls: [
            { name: 'util.fix', line: 8, target: 'pkg/util.py::fix' },
            { name: 'fmt', line: 9, target: 'app.py::fmt' },
            { name: 'x.strip', line: 8, target: null },
          ],
        },
        {
          id: 'app.py::fmt',
          name: 'fmt',
          qualname: 'fmt',
          line_start: 11,
          line_end: 12,
          steps: [{ id: 's1', kind: 'return', label: 'return str(n)', line_start: 12, line_end: 12 }],
          edges: [],
          calls: [
            { name: 'str', line: 12, target: null },
            { name: 'util.fix', line: 12, target: 'pkg/util.py::fix' },
          ],
        },
      ],
    },
    {
      path: 'pkg/util.py',
      line_count: 2,
      parse_error: null,
      imports: [],
      functions: [
        {
          id: 'pkg/util.py::fix',
          name: 'fix',
          qualname: 'fix',
          line_start: 1,
          line_end: 2,
          steps: [{ id: 's1', kind: 'return', label: 'return abs(x)', line_start: 2, line_end: 2 }],
          edges: [],
          calls: [],
        },
      ],
    },
    { path: 'broken.py', line_count: 2, parse_error: 'line 1: invalid syntax', imports: [], functions: [] },
  ],
  file_edges: [
    { source: 'app.py', target: 'pkg/util.py', kind: 'call' },
    { source: 'app.py', target: 'pkg/util.py', kind: 'import' },
  ],
  skipped: [],
}

export const SCRIPT_MODEL: RepoModel = {
  files: [
    {
      path: 'run.py',
      line_count: 2,
      parse_error: null,
      imports: [],
      functions: [
        {
          id: 'run.py::<module>',
          name: '<module>',
          qualname: '<module>',
          line_start: 1,
          line_end: 2,
          steps: [{ id: 's1', kind: 'block', label: 'x = 1', line_start: 1, line_end: 2 }],
          edges: [],
          calls: [],
        },
      ],
    },
  ],
  file_edges: [],
  skipped: [],
}
