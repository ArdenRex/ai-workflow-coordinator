// src/hooks/useTasks.js
import { useState, useEffect, useCallback, useRef } from "react";
import { fetchTasks, updateTaskStatus, processMessage } from "../api";

const POLL_INTERVAL = 15_000; // re-fetch every 15 s to catch Slack-created tasks

export function useTasks(filters = {}) {
  const [tasks, setTasks]         = useState([]);
  const [total, setTotal]         = useState(0);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Track mounted state to prevent setState after unmount
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Stable ref to filters to avoid triggering useEffect on every render
  const filtersRef = useRef(filters);
  useEffect(() => { filtersRef.current = filters; });

  const load = useCallback(async (silent = false) => {
    if (!mountedRef.current) return;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await fetchTasks(filtersRef.current);
      if (!mountedRef.current) return;
      setTasks(data.tasks ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      if (!mountedRef.current) return;
      setError(e.message ?? "Failed to load tasks.");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []); // no deps — filtersRef.current is always fresh

  // Initial load + polling
  useEffect(() => {
    load();
    const id = setInterval(() => load(true), POLL_INTERVAL);
    return () => clearInterval(id);
  }, [load]);

  // Optimistic status update
  const moveTask = useCallback(async (taskId, newStatus) => {
    // Snapshot for rollback
    const snapshot = tasks;

    setTasks(prev =>
      prev.map(t => t.id === taskId ? { ...t, status: newStatus } : t)
    );
    setError(null);

    try {
      const updated = await updateTaskStatus(taskId, newStatus);
      if (!mountedRef.current) return;
      // Replace with server-confirmed state
      setTasks(prev => prev.map(t => t.id === taskId ? updated : t));
    } catch (e) {
      if (!mountedRef.current) return;
      // Roll back to snapshot instead of full reload
      setTasks(snapshot);
      setError(e.message ?? "Failed to update task status.");
    }
  }, [tasks]);

  // Add task via AI extraction
  const addTask = useCallback(async (message) => {
    if (!message?.trim()) {
      throw new Error("Message must not be empty.");
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await processMessage(message);
      if (!mountedRef.current) return result;
      setTasks(prev => [result.task, ...prev]);
      setTotal(n => n + 1);
      return result;
    } catch (e) {
      if (!mountedRef.current) throw e;
      setError(e.message ?? "Failed to process message.");
      throw e;   // re-throw so the caller (form) can react (clear input, show toast, etc.)
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  }, []);

  return {
    tasks,
    total,
    loading,
    error,
    submitting,
    moveTask,
    addTask,
    reload: load,
    clearError: () => setError(null),
  };
}
