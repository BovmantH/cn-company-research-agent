import { useEffect, useRef, useState } from 'react';

import {
  loadCapabilities,
  resolveCompany,
  type CapabilityLoadState,
  type PublicCompanyIdentity,
} from '../api/companyIntelligence';
import type { ResearchFormValues } from './model';
import type { ProfessionalResearchAcceptance } from './researchRequest';


export type CompanyCandidateView = Omit<
  PublicCompanyIdentity,
  'resolution_token'
> & { view_id: string };

export type ProfessionalFlowState =
  | { status: 'idle' }
  | { status: 'resolving'; query: string }
  | { status: 'candidates'; query: string; candidates: CompanyCandidateView[] }
  | {
      status: 'fallback';
      query: string;
      reason: 'not_found' | 'blocked' | 'in_progress' | 'unavailable';
    };

export type PreparedResearch = {
  values: ResearchFormValues;
  resolutionToken: string | null;
};

type PreparationOutcome =
  | { kind: 'ready'; prepared: PreparedResearch }
  | { kind: 'pending' };

const normalizeQuery = (query: string): string => query
  .normalize('NFKC')
  .trim()
  .replace(/\s+/g, ' ');

const createIdempotencyKey = (): string => `resolve-${crypto.randomUUID()}`;
const CAPABILITY_TIMEOUT_MS = 8_000;
const RESOLUTION_TIMEOUT_MS = 30_000;

/**
 * 托管专业数据的异步准备流程。Token、幂等键和表单快照只保存在私有 ref，
 * 不进入可渲染 state；取消后通过 generation 丢弃晚到响应。
 */
export const useProfessionalResearchFlow = (apiUrl: string) => {
  const [capabilityState, setCapabilityState] = useState<CapabilityLoadState>({
    status: 'loading',
  });
  const [flowState, setFlowState] = useState<ProfessionalFlowState>({
    status: 'idle',
  });
  const generationRef = useRef(0);
  const inFlightRef = useRef(false);
  const pendingValuesRef = useRef<ResearchFormValues | null>(null);
  const tokenVaultRef = useRef(new Map<string, string>());
  const idempotencyKeysRef = useRef(new Map<string, string>());
  const activeQueryRef = useRef<string | null>(null);
  const resolveAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeoutId = globalThis.setTimeout(() => {
      controller.abort();
      if (active) {
        setCapabilityState({ status: 'unavailable', reason: 'request_failed' });
      }
    }, CAPABILITY_TIMEOUT_MS);
    void loadCapabilities(apiUrl, controller.signal).then((state) => {
      if (active) {
        globalThis.clearTimeout(timeoutId);
        setCapabilityState(state);
      }
    });
    return () => {
      active = false;
      globalThis.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [apiUrl]);

  useEffect(() => () => {
    generationRef.current += 1;
    inFlightRef.current = false;
    resolveAbortRef.current?.abort();
    resolveAbortRef.current = null;
    pendingValuesRef.current = null;
    tokenVaultRef.current.clear();
  }, []);

  const clearPending = () => {
    pendingValuesRef.current = null;
    tokenVaultRef.current.clear();
  };

  const cancel = () => {
    generationRef.current += 1;
    resolveAbortRef.current?.abort();
    resolveAbortRef.current = null;
    inFlightRef.current = false;
    clearPending();
    setFlowState({ status: 'idle' });
  };

  const prepare = async (
    values: ResearchFormValues,
  ): Promise<PreparationOutcome> => {
    if (!values.professionalDataRequested) {
      return { kind: 'ready', prepared: { values, resolutionToken: null } };
    }
    if (inFlightRef.current) return { kind: 'pending' };

    const capabilityAvailable = capabilityState.status === 'ready'
      && capabilityState.capability.enabled;
    if (!capabilityAvailable) {
      pendingValuesRef.current = values;
      setFlowState({
        status: 'fallback',
        query: values.companyName,
        reason: 'unavailable',
      });
      return { kind: 'pending' };
    }

    inFlightRef.current = true;
    clearPending();
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    const query = normalizeQuery(values.companyName);
    activeQueryRef.current = query;
    const idempotencyKey = idempotencyKeysRef.current.get(query)
      || createIdempotencyKey();
    idempotencyKeysRef.current.set(query, idempotencyKey);
    const controller = new AbortController();
    resolveAbortRef.current = controller;
    const timeoutId = globalThis.setTimeout(
      () => controller.abort(),
      RESOLUTION_TIMEOUT_MS,
    );
    setFlowState({ status: 'resolving', query });

    try {
      const resolution = await resolveCompany(
        apiUrl,
        query,
        idempotencyKey,
        controller.signal,
      );
      if (generation !== generationRef.current) return { kind: 'pending' };

      if (resolution.kind === 'exact') {
        setFlowState({ status: 'idle' });
        return {
          kind: 'ready',
          prepared: {
            values,
            resolutionToken: resolution.identity.resolution_token,
          },
        };
      }

      pendingValuesRef.current = values;
      if (resolution.kind === 'candidates') {
        const candidates = resolution.candidates.map((candidate) => {
          const viewId = crypto.randomUUID();
          tokenVaultRef.current.set(
            viewId,
            candidate.resolution_token,
          );
          const { resolution_token: _token, ...view } = candidate;
          return { ...view, view_id: viewId };
        });
        setFlowState({ status: 'candidates', query, candidates });
      } else {
        setFlowState({
          status: 'fallback',
          query,
          reason: resolution.kind === 'not_found'
            ? 'not_found'
            : resolution.reason === 'resolution_in_progress'
              ? 'in_progress'
              : 'blocked',
        });
      }
      return { kind: 'pending' };
    } catch {
      if (generation !== generationRef.current) return { kind: 'pending' };
      pendingValuesRef.current = values;
      setFlowState({ status: 'fallback', query, reason: 'unavailable' });
      return { kind: 'pending' };
    } finally {
      globalThis.clearTimeout(timeoutId);
      if (generation === generationRef.current) {
        inFlightRef.current = false;
        resolveAbortRef.current = null;
      }
    }
  };

  const selectCandidate = (viewId: string): PreparedResearch | null => {
    const values = pendingValuesRef.current;
    const resolutionToken = tokenVaultRef.current.get(viewId);
    if (!values || !resolutionToken) return null;
    const prepared = { values, resolutionToken };
    clearPending();
    setFlowState({ status: 'idle' });
    return prepared;
  };

  const continueBasic = (): PreparedResearch | null => {
    const values = pendingValuesRef.current;
    if (!values) return null;
    const prepared = {
      values: { ...values, professionalDataRequested: false },
      resolutionToken: null,
    };
    clearPending();
    setFlowState({ status: 'idle' });
    return prepared;
  };

  const markResearchAccepted = (
    professionalData: ProfessionalResearchAcceptance | null,
  ) => {
    const tokenWasConsumed = professionalData !== null && (
      professionalData.status === 'accepted'
      || professionalData.status === 'in_progress'
      || professionalData.status === 'replayed'
      || (
        professionalData.status === 'degraded'
        && professionalData.reason === 'identity_unconfirmed'
      )
    );
    if (tokenWasConsumed && activeQueryRef.current) {
      idempotencyKeysRef.current.delete(activeQueryRef.current);
      activeQueryRef.current = null;
    }
    clearPending();
  };

  return {
    capabilityState,
    flowState,
    prepare,
    selectCandidate,
    continueBasic,
    markResearchAccepted,
    cancel,
  };
};
