import {
  buildAttentionItems,
  getNextLeadId,
  getRunActions,
  getRunStatusLabel,
  getWorkerHealthTone,
  isWorkbenchEmpty,
  leadActionRequiresReason,
} from '../../client/src/features/operator/operator-view-model';
import type { OperatorSkillRun, OperatorWorkbench } from '../../client/src/types/operator';


const emptyWorkbench: OperatorWorkbench = {
  generated_at: '2026-07-15T01:00:00+00:00',
  attention: {
    review_queue: 0,
    running_skills: 0,
    failed_tasks: 0,
    stale_workers: 0,
  },
  lead_queue: [],
  skill_runs: [],
  task_failures: [],
  workers: [],
  next_action: {
    kind: 'none',
    title: '当前没有紧急事项',
    description: '系统队列平稳。',
    target: '/campaigns',
  },
};


describe('operator view model', () => {
  it('prioritizes failed tasks as urgent attention', () => {
    const items = buildAttentionItems({
      ...emptyWorkbench.attention,
      review_queue: 8,
      failed_tasks: 2,
    });

    expect(items[0]).toMatchObject({ key: 'failed_tasks', tone: 'danger', value: 2 });
    expect(items[1]).toMatchObject({ key: 'review_queue', tone: 'warning', value: 8 });
  });

  it('formats an empty workbench without fake metrics', () => {
    expect(isWorkbenchEmpty(emptyWorkbench)).toBe(true);
    expect(buildAttentionItems(emptyWorkbench.attention).map((item) => item.value)).toEqual([0, 0, 0, 0]);
  });

  it('marks stale workers as degraded', () => {
    expect(getWorkerHealthTone('stale')).toBe('danger');
    expect(getWorkerHealthTone('healthy')).toBe('success');
  });

  it('advances lead review and enforces reasoned judgments', () => {
    expect(getNextLeadId([{ id: 1 }, { id: 2 }, { id: 3 }], 2)).toBe(3);
    expect(leadActionRequiresReason('invalid')).toBe(true);
    expect(leadActionRequiresReason('valid')).toBe(false);
  });

  it('maps run states to operator actions', () => {
    const run = { status: 'previewed' } as OperatorSkillRun;
    expect(getRunStatusLabel('previewed')).toBe('已预览');
    expect(getRunActions(run)).toEqual(['queue', 'cancel', 'copy']);
  });
});
