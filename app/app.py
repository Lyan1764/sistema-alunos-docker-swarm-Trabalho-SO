"""
Cadastro de Alunos Distribuído
==============================
Trabalho Final de Sistemas Operacionais (UFPI - Picos) - Docker.

Aplicação web simples (Python + Flask) que cadastra, consulta, altera e exclui alunos (por matrícula) em um
banco NoSQL (MongoDB) executando como *replica set* de 3 containers.

Pontos principais do código:
  1. Conexão com o replica set (MONGO_URI)               -> seção "Conexão"
  2. Adicionar registros (POST /api/alunos)               -> seção "Rotas da API"
  3. Recuperar registros com consultas (GET /api/alunos)  -> seção "Rotas da API"
  4. Status do cluster (GET /api/status)                  -> mostra quem é PRIMARY/SECONDARY
"""
import os
import re
import socket
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from pymongo import ASCENDING, MongoClient, ReadPreference, UpdateOne
from pymongo.errors import DuplicateKeyError, PyMongoError

# ---------------------------------------------------------------------------
# Conexão com o MongoDB
# ---------------------------------------------------------------------------
# A URI lista os três nós do replica set "rs0". Os nomes (mongo1, mongo2, mongo3)
# são resolvidos pelo DNS interno do Docker (rede do Compose ou overlay do Swarm).
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
)
DB_NAME = os.getenv("MONGO_DB", "escola")

# - w="majority": a escrita só é confirmada quando a maioria dos nós (2 de 3) a gravou.
# - primaryPreferred: lê do primário; se ele cair, lê de um secundário (a app não "morre").
# - serverSelectionTimeoutMS: tempo máximo esperando algum nó ficar disponível.
client = MongoClient(
    MONGO_URI,
    w="majority",
    readPreference="primaryPreferred",
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=4000,
)

_indices_criados = False
_trava = threading.Lock()


def alunos():
    """Retorna a coleção 'alunos' e garante (uma única vez) que os índices existam."""
    global _indices_criados
    col = client[DB_NAME]["alunos"]
    if not _indices_criados:
        with _trava:
            if not _indices_criados:
                col.create_index([("matricula", ASCENDING)], unique=True, name="uniq_matricula")
                col.create_index([("curso", ASCENDING)], name="idx_curso")
                _indices_criados = True
    return col


app = Flask(__name__)
app.json.ensure_ascii = False  # mantém acentos no JSON
HOSTNAME = socket.gethostname()  # id do container (mostra o balanceamento no Swarm)


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def serializar(doc):
    """Converte um documento do MongoDB em algo que o jsonify entende."""
    doc = dict(doc)
    doc.pop("_id", None)  # a chave pública do aluno é a matrícula
    if isinstance(doc.get("criado_em"), datetime):
        doc["criado_em"] = doc["criado_em"].isoformat()
    return doc


def endereco(par):
    """(host, porta) -> 'host:porta'."""
    return f"{par[0]}:{par[1]}" if par else None


STATUS_VALIDOS = ("Ativo", "Trancado", "Formado")


def validar_aluno(dados, parcial=False):
    """Valida o JSON recebido. Retorna (campos, erro). parcial=True para atualização."""
    if not isinstance(dados, dict):
        return None, "Envie um JSON válido."
    campos = {}

    if not parcial or "matricula" in dados:
        matricula = str(dados.get("matricula", "")).strip()
        if not re.fullmatch(r"\d{5,15}", matricula):
            return None, "A matrícula deve ter de 5 a 15 dígitos."
        campos["matricula"] = matricula
    if not parcial or "nome" in dados:
        nome = str(dados.get("nome", "")).strip()
        if not nome or len(nome) > 120:
            return None, "Informe o nome (até 120 caracteres)."
        campos["nome"] = nome
    if not parcial or "curso" in dados:
        curso = str(dados.get("curso", "")).strip()
        if not curso or len(curso) > 80:
            return None, "Informe o curso (até 80 caracteres)."
        campos["curso"] = curso
    if not parcial or "periodo" in dados:
        try:
            periodo = int(dados.get("periodo"))
        except (TypeError, ValueError):
            return None, "O período deve ser um número inteiro."
        if not (1 <= periodo <= 20):
            return None, "O período deve estar entre 1 e 20."
        campos["periodo"] = periodo
    if "email" in dados or not parcial:
        email = str(dados.get("email", "")).strip()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return None, "E-mail inválido."
        campos["email"] = email
    if "status" in dados or not parcial:
        status = str(dados.get("status", "Ativo")).strip() or "Ativo"
        if status not in STATUS_VALIDOS:
            return None, "Status deve ser: " + ", ".join(STATUS_VALIDOS) + "."
        campos["status"] = status

    if not parcial:
        campos["criado_em"] = datetime.now(timezone.utc)
    return campos, None


# ---------------------------------------------------------------------------
# Tratamento de erros do banco: devolve 503 em vez de derrubar a aplicação
# ---------------------------------------------------------------------------
@app.errorhandler(DuplicateKeyError)
def erro_duplicado(e):
    return jsonify(erro="Já existe um aluno com essa matrícula."), 409


@app.errorhandler(PyMongoError)
def erro_banco(e):
    app.logger.error("Erro no MongoDB: %s", e)
    return jsonify(
        erro="Banco de dados indisponível no momento. Tente novamente em alguns segundos."
    ), 503


# ---------------------------------------------------------------------------
# Rotas da interface e de saúde
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    """Usado pelo HEALTHCHECK do Docker. Não depende do banco."""
    return jsonify(status="ok", container=HOSTNAME)


# ---------------------------------------------------------------------------
# Rotas da API
# ---------------------------------------------------------------------------
@app.post("/api/alunos")
def adicionar_aluno():
    """ADICIONAR: matricula um novo aluno no MongoDB."""
    doc, erro = validar_aluno(request.get_json(silent=True))
    if erro:
        return jsonify(erro=erro), 400
    alunos().insert_one(doc)  # matrícula repetida -> DuplicateKeyError -> 409
    return jsonify(
        aluno=serializar(doc),
        gravado_em=endereco(client.primary),  # nó PRIMARY que recebeu a escrita
        container=HOSTNAME,
    ), 201


@app.get("/api/alunos")
def listar_alunos():
    """RECUPERAR: consulta alunos (?busca=nome/matrícula&curso=...&status=...)."""
    filtro = {}
    busca = request.args.get("busca", "").strip()
    if busca:
        padrao = {"$regex": re.escape(busca), "$options": "i"}  # contém, sem diferenciar maiúsculas
        filtro["$or"] = [{"nome": padrao}, {"matricula": padrao}]
    curso = request.args.get("curso", "").strip()
    if curso:
        filtro["curso"] = curso
    status = request.args.get("status", "").strip()
    if status:
        filtro["status"] = status
    try:
        limite = max(1, min(int(request.args.get("limite", 100)), 200))
    except ValueError:
        limite = 100

    cursor = alunos().find(filtro).sort("nome", ASCENDING).limit(limite)
    docs = [serializar(d) for d in cursor]
    return jsonify(
        total=len(docs),
        alunos=docs,
        lido_de=endereco(cursor.address),  # nó do cluster que respondeu a consulta
        container=HOSTNAME,
    )


@app.get("/api/alunos/<matricula>")
def obter_aluno(matricula):
    doc = alunos().find_one({"matricula": matricula})
    if doc is None:
        return jsonify(erro="Aluno não encontrado."), 404
    return jsonify(aluno=serializar(doc))


@app.patch("/api/alunos/<matricula>")
def atualizar_aluno(matricula):
    """Altera nome, curso, período, e-mail ou status (ex.: {"status": "Trancado"})."""
    campos, erro = validar_aluno(request.get_json(silent=True), parcial=True)
    campos = {k: v for k, v in (campos or {}).items() if k != "matricula"}
    if erro or not campos:
        return jsonify(erro=erro or "Nada para atualizar."), 400
    r = alunos().update_one({"matricula": matricula}, {"$set": campos})
    if r.matched_count == 0:
        return jsonify(erro="Aluno não encontrado."), 404
    return jsonify(ok=True)


@app.delete("/api/alunos/<matricula>")
def remover_aluno(matricula):
    """EXCLUIR: remove o aluno pela matrícula."""
    r = alunos().delete_one({"matricula": matricula})
    if r.deleted_count == 0:
        return jsonify(erro="Aluno não encontrado."), 404
    return jsonify(ok=True)


@app.get("/api/estatisticas")
def estatisticas():
    """Consulta agregada (aggregation pipeline): alunos por curso."""
    pipeline = [
        {"$group": {
            "_id": "$curso",
            "total": {"$sum": 1},
            "ativos": {"$sum": {"$cond": [{"$eq": ["$status", "Ativo"]}, 1, 0]}},
            "media_periodo": {"$avg": "$periodo"},
        }},
        {"$sort": {"total": -1, "_id": 1}},
    ]
    por_curso = [
        {"curso": r["_id"], "total": r["total"], "ativos": r["ativos"],
         "media_periodo": round(r["media_periodo"], 1)}
        for r in alunos().aggregate(pipeline)
    ]
    return jsonify(total_alunos=sum(c["total"] for c in por_curso), por_curso=por_curso)


@app.post("/api/exemplos")
def carregar_exemplos():
    """Carrega alguns alunos de exemplo (não duplica se a matrícula já existir)."""
    exemplos = [
        ("20240001", "Ana Beatriz Lima", "Sistemas de Informação", 5, "ana@exemplo.com", "Ativo"),
        ("20240002", "Carlos Eduardo Sousa", "Sistemas de Informação", 5, "carlos@exemplo.com", "Ativo"),
        ("20240003", "Maria Clara Alves", "Sistemas de Informação", 3, "maria@exemplo.com", "Ativo"),
        ("20230010", "João Pedro Ribeiro", "Sistemas de Informação", 7, "joao@exemplo.com", "Trancado"),
        ("20240101", "Fernanda Costa", "Enfermagem", 4, "fernanda@exemplo.com", "Ativo"),
        ("20240102", "Rafael Nunes", "Enfermagem", 6, "rafael@exemplo.com", "Ativo"),
        ("20230201", "Beatriz Santos", "Administração", 8, "beatriz@exemplo.com", "Ativo"),
        ("20220202", "Lucas Martins", "Administração", 9, "lucas@exemplo.com", "Formado"),
    ]
    agora = datetime.now(timezone.utc)
    operacoes = [
        UpdateOne(
            {"matricula": m},
            {"$setOnInsert": {"matricula": m, "nome": n, "curso": c, "periodo": p,
                              "email": e, "status": st, "criado_em": agora}},
            upsert=True,
        )
        for (m, n, c, p, e, st) in exemplos
    ]
    r = alunos().bulk_write(operacoes)
    return jsonify(inseridos=r.upserted_count), 201


@app.get("/api/status")
def status_cluster():
    """Mostra o estado do replica set (quem é PRIMARY e quem é SECONDARY)."""
    estado = client.admin.command(
        "replSetGetStatus", read_preference=ReadPreference.PRIMARY_PREFERRED
    )
    membros = [
        {
            "nome": m["name"],
            "estado": m["stateStr"],  # PRIMARY, SECONDARY, (not reachable/healthy)...
            "saudavel": m.get("health") == 1,
        }
        for m in estado["members"]
    ]
    return jsonify(
        replica_set=estado["set"],
        membros=membros,
        container=HOSTNAME,
    )


if __name__ == "__main__":
    # Execução direta (desenvolvimento). No container usamos o gunicorn.
    app.run(host="0.0.0.0", port=8000, debug=False)
