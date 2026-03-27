// src/hooks/useTasks.js
import { useState, useEffect, useCallback, useRef } from "react";
import { fetchTasks, updateTaskStatus, processMessage, deleteTask } from "../api";

const POLL_INTERVAL = 15_000;

export function useTasks(filters = {}) {
  const [tasks, setTasks]           = useState([]);
  const [total, setTotal]           = useState(0);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

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
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => load(true), POLL_INTERVAL);
    return () => clearInterval(id);
  }, [load]);

  // Optimistic status update
  const moveTask = useCallback(async (taskId, newStatus) => {
    const snapshot = tasks;
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: newStatus } : t));
    setError(null);
    try {
      const updated = await updateTaskStatus(taskId, newStatus);
      if (!mountedRef.current) return;
      setTasks(prev => prev.map(t => t.id === taskId ? updated : t));
    } catch (e) {
      if (!mountedRef.current) return;
      setTasks(snapshot);
      setError(e.message ?? "Failed to update task status.");
    }
  }, [tasks]);

  // Optimistic delete
  const removeTask = useCallback(async (taskId) => {
    const snapshot = tasks;
    setTasks(prev => prev.filter(t => t.id !== taskId));
    setTotal(n => Math.max(0, n - 1));
    setError(null);
    try {
      await deleteTask(taskId);
    } catch (e) {
      if (!mountedRef.current) return;
      setTasks(snapshot);
      setTotal(n => n + 1);
      setError(e.message ?? "Failed to delete task.");
    }
  }, [tasks]);

  // Add task via AI extraction
  const addTask = useCallback(async (message) => {
    if (!message?.trim()) throw new Error("Message must not be empty.");
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
      throw e;
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
    removeTask,
    addTask,
    reload: load,
    clearError: () => setError(null),
  };
}
