import express from 'express';
import cors from 'cors';
import { getMarketStatus, updateMarketSchedule, getSchedule } from './routes/marketRoutes.js';

const app = express();
app.use(express.json());
app.use(cors());

// Routes
app.get('/api/market/status', getMarketStatus);
app.get('/api/admin/market/schedule', getSchedule);
app.post('/api/admin/market/schedule', updateMarketSchedule);

const PORT = 4000;
app.listen(PORT, () => console.log(`✅ Server running on port ${PORT}`));






import sqlite3 from 'sqlite3';
import { open } from 'sqlite';

export async function connectDB() {
  return open({
    filename: './market.db',
    driver: sqlite3.Database,
  });
}





import { connectDB } from '../db.js';

export async function initDB() {
  const db = await connectDB();
  await db.exec(`
    CREATE TABLE IF NOT EXISTS market_schedule (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      market_open_time TEXT,
      market_close_time TEXT,
      is_open_today INTEGER,
      manual_override INTEGER,
      manual_status TEXT,
      updated_by TEXT,
      updated_at TEXT
    )
  `);
  return db;
}

export async function getScheduleFromDB() {
  const db = await initDB();
  return db.get('SELECT * FROM market_schedule ORDER BY id DESC LIMIT 1');
}

export async function updateScheduleInDB(data) {
  const db = await initDB();
  await db.run(
    `INSERT INTO market_schedule 
     (market_open_time, market_close_time, is_open_today, manual_override, manual_status, updated_by, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, datetime('now'))`,
    [data.market_open_time, data.market_close_time, data.is_open_today, data.manual_override, data.manual_status, data.updated_by]
  );
}





import { getScheduleFromDB, updateScheduleInDB } from '../models/marketScheduleModel.js';

export async function getMarketStatus(req, res) {
  const schedule = await getScheduleFromDB();
  if (!schedule) return res.json({ status: 'closed', reason: 'No schedule found' });

  if (schedule.manual_override) {
    return res.json({ status: schedule.manual_status });
  }

  const now = new Date();
  const currentTime = now.toTimeString().slice(0, 5);
  const isOpen = currentTime >= schedule.market_open_time && currentTime <= schedule.market_close_time;

  res.json({ status: isOpen ? 'open' : 'closed' });
}

export async function updateMarketSchedule(req, res) {
  await updateScheduleInDB(req.body);
  res.json({ success: true, message: 'Market schedule updated' });
}

export async function getSchedule(req, res) {
  const schedule = await getScheduleFromDB();
  res.json(schedule || {});
}





import React, { useEffect, useState } from 'react';
import axios from 'axios';

export default function MarketAdminPanel() {
  const [schedule, setSchedule] = useState({});
  const [form, setForm] = useState({
    market_open_time: '',
    market_close_time: '',
    is_open_today: true,
    manual_override: false,
    manual_status: 'closed',
    updated_by: 'admin'
  });

  useEffect(() => {
    axios.get('http://localhost:4000/api/admin/market/schedule').then(res => {
      setSchedule(res.data || {});
    });
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    await axios.post('http://localhost:4000/api/admin/market/schedule', form);
    alert('Schedule updated!');
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>📊 Market Schedule Admin Panel</h2>
      <p>Current Status: <b>{schedule.manual_status || 'N/A'}</b></p>
      <form onSubmit={handleSubmit}>
        <div>
          <label>Open Time: </label>
          <input type="time" onChange={e => setForm({ ...form, market_open_time: e.target.value })} />
        </div>
        <div>
          <label>Close Time: </label>
          <input type="time" onChange={e => setForm({ ...form, market_close_time: e.target.value })} />
        </div>
        <div>
          <label>Manual Override: </label>
          <input type="checkbox" onChange={e => setForm({ ...form, manual_override: e.target.checked })} />
        </div>
        <div>
          <label>Status (if override): </label>
          <select onChange={e => setForm({ ...form, manual_status: e.target.value })}>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        </div>
        <button type="submit">Save Schedule</button>
      </form>
    </div>
  );
}




import React from 'react';
import MarketAdminPanel from './components/MarketAdminPanel';

function App() {
  return (
    <div className="App">
      <h1>Stock Trading System - Admin Portal</h1>
      <MarketAdminPanel />
    </div>
  );
}

export default App;



cd backend
npm install express cors sqlite sqlite3
node server.js




cd frontend
npm install react axios
npm start
