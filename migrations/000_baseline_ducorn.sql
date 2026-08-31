-- DuCorn schema baseline: ducorn
-- Captured 2026-08-31 by scripts/migrate.py --baseline
-- This describes objects that ALREADY EXIST. It is recorded as
-- applied and is never replayed against a live database; its job
-- is to let you rebuild from nothing.

--
-- PostgreSQL database dump
--

\restrict GlysRxg8X5bHtB1HhUtdCOt7DM9PsKml2tw2Bp7hBHDrmqUMKapSB5cgMUoH6qd

-- Dumped from database version 16.14 (Homebrew)
-- Dumped by pg_dump version 16.14 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_activity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_activity (
    id integer NOT NULL,
    agent_id character varying(20) NOT NULL,
    task_name character varying(100) NOT NULL,
    status character varying(20) NOT NULL,
    summary text,
    tokens_used integer DEFAULT 0,
    cost_usd numeric(10,6) DEFAULT 0,
    model_used character varying(50),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT agent_activity_status_check CHECK (((status)::text = ANY ((ARRAY['started'::character varying, 'completed'::character varying, 'failed'::character varying, 'blocked'::character varying])::text[])))
);


--
-- Name: agent_activity_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_activity_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_activity_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_activity_id_seq OWNED BY public.agent_activity.id;


--
-- Name: approval_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_requests (
    id integer NOT NULL,
    requested_by character varying(20) NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    document_path text,
    status character varying(20) DEFAULT 'pending'::character varying,
    decided_by character varying(50),
    decided_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT approval_requests_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
);


--
-- Name: approval_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_requests_id_seq OWNED BY public.approval_requests.id;


--
-- Name: daily_digests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_digests (
    id integer NOT NULL,
    digest_date date NOT NULL,
    content text NOT NULL,
    audio_path text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: daily_digests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_digests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_digests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_digests_id_seq OWNED BY public.daily_digests.id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id integer NOT NULL,
    title character varying(200) NOT NULL,
    doc_type character varying(50),
    file_path text,
    created_by character varying(20),
    status character varying(20) DEFAULT 'draft'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;


--
-- Name: founder_notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.founder_notes (
    id integer NOT NULL,
    text text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    done boolean DEFAULT false NOT NULL,
    done_by text,
    done_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: founder_notes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.founder_notes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: founder_notes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.founder_notes_id_seq OWNED BY public.founder_notes.id;


--
-- Name: pipeline_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_runs (
    id integer NOT NULL,
    slug character varying(200) NOT NULL,
    product_name character varying(200),
    complexity character varying(20) DEFAULT 'medium'::character varying,
    status character varying(50) DEFAULT 'started'::character varying,
    current_skill character varying(100),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    cost_so_far numeric(10,4) DEFAULT 0,
    estimated_cost character varying(50),
    prd_path character varying(500),
    error_message text,
    build_engine character varying(20) DEFAULT 'fast'::character varying,
    coder character varying(20) DEFAULT 'crewai'::character varying,
    environment character varying(20) DEFAULT 'test'::character varying,
    has_ui boolean DEFAULT true NOT NULL,
    design_model text
);


--
-- Name: pipeline_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pipeline_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pipeline_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pipeline_runs_id_seq OWNED BY public.pipeline_runs.id;


--
-- Name: pipeline_skill_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_skill_runs (
    id integer NOT NULL,
    pipeline_id integer,
    skill_name character varying(100),
    status character varying(50) DEFAULT 'waiting'::character varying,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    cost numeric(10,4) DEFAULT 0,
    output_summary text
);


--
-- Name: pipeline_skill_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pipeline_skill_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pipeline_skill_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pipeline_skill_runs_id_seq OWNED BY public.pipeline_skill_runs.id;


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_activity id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_activity ALTER COLUMN id SET DEFAULT nextval('public.agent_activity_id_seq'::regclass);


--
-- Name: approval_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests ALTER COLUMN id SET DEFAULT nextval('public.approval_requests_id_seq'::regclass);


--
-- Name: daily_digests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_digests ALTER COLUMN id SET DEFAULT nextval('public.daily_digests_id_seq'::regclass);


--
-- Name: documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents ALTER COLUMN id SET DEFAULT nextval('public.documents_id_seq'::regclass);


--
-- Name: founder_notes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.founder_notes ALTER COLUMN id SET DEFAULT nextval('public.founder_notes_id_seq'::regclass);


--
-- Name: pipeline_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs ALTER COLUMN id SET DEFAULT nextval('public.pipeline_runs_id_seq'::regclass);


--
-- Name: pipeline_skill_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_skill_runs ALTER COLUMN id SET DEFAULT nextval('public.pipeline_skill_runs_id_seq'::regclass);


--
-- Name: agent_activity agent_activity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_activity
    ADD CONSTRAINT agent_activity_pkey PRIMARY KEY (id);


--
-- Name: approval_requests approval_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_pkey PRIMARY KEY (id);


--
-- Name: daily_digests daily_digests_digest_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_digests
    ADD CONSTRAINT daily_digests_digest_date_key UNIQUE (digest_date);


--
-- Name: daily_digests daily_digests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_digests
    ADD CONSTRAINT daily_digests_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: founder_notes founder_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.founder_notes
    ADD CONSTRAINT founder_notes_pkey PRIMARY KEY (id);


--
-- Name: pipeline_runs pipeline_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_pkey PRIMARY KEY (id);


--
-- Name: pipeline_runs pipeline_runs_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_slug_key UNIQUE (slug);


--
-- Name: pipeline_skill_runs pipeline_skill_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_skill_runs
    ADD CONSTRAINT pipeline_skill_runs_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: founder_notes_open_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX founder_notes_open_idx ON public.founder_notes USING btree (done, created_at DESC);


--
-- Name: pipeline_skill_runs pipeline_skill_runs_pipeline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_skill_runs
    ADD CONSTRAINT pipeline_skill_runs_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.pipeline_runs(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict GlysRxg8X5bHtB1HhUtdCOt7DM9PsKml2tw2Bp7hBHDrmqUMKapSB5cgMUoH6qd

