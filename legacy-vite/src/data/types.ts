export interface ChainPoint {
  date: string;
  txs: number;
  blocks: number;
  dau_signers: number;
  mau_signers: number;
  distinct_recipients: number;
  /** Set when the index stops part-way through this UTC day. */
  partial?: boolean;
}

export interface PsPoint {
  date: string;
  new_users: number;
  registered_cumulative: number;
  dau: number;
  mau: number;
  actions: number;
  partial?: boolean;
}

/** Last point that covers a whole UTC day — the right basis for a headline. */
export const lastComplete = <T extends { partial?: boolean }>(rows: T[]): T | undefined => {
  for (let i = rows.length - 1; i >= 0; i--) if (!rows[i].partial) return rows[i];
  return rows[rows.length - 1];
};

export interface StakingPoint {
  date: string;
  new_stakers: number;
  cumulative_stakers: number;
  dau: number;
  mau: number;
}

export interface Dataset {
  generated_at: string;
  partial_day: string | null;
  chain: {
    series: ChainPoint[];
    monthly: { month: string; mau_signers: number; txs: number }[];
    top_senders: { address: string; txs: number }[];
    total_txs: number;
    total_distinct_senders: number;
  };
  predictstreet: {
    series: PsPoint[];
    monthly: { month: string; mau: number; new_users: number }[];
    registered_total: number;
    distinct_owners: number;
    owners_that_self_signed: number;
    vaults_that_sent_txs: number;
    signer_visible_pct: number;
    event_mix: { sig: string; count: number }[];
  } | null;
  staking: {
    series: StakingPoint[];
    unique_stakers: number;
    event_counts: Record<string, number>;
  } | null;
  meta: {
    adi_chain_id: number;
    adi_rpc: string;
    adi_explorer: string;
    rolling_window_days: number;
    contracts: Record<string, string>;
  };
}
