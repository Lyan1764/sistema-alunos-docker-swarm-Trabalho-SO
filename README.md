# 🎓 Cadastro de Alunos Distribuído — Trabalho Final de Docker

**Disciplina:** Sistemas Operacionais — 2026.2 · **Prof.:** Thiago José Barbosa Lima
**Curso:** Bacharelado em Sistemas de Informação — UFPI, Campus Senador Helvídio Nunes de Barros (Picos)
**Equipe:** Lyan Fernando · Ryan Feitosa· Mateus Felipe

---

## 1. Descrição da aplicação

Aplicação web para **cadastro e consulta de alunos**, identificados pela **matrícula**. Pela interface (ou pela API REST) é possível:

- **matricular** (adicionar) alunos: matrícula, nome, curso, período e e-mail; a matrícula é única (repetida retorna erro 409);
- **recuperar** alunos por meio de consultas: busca por nome ou matrícula, filtro por curso e por situação (Ativo, Trancado, Formado);
- **alterar** dados (trancar/reativar a matrícula, mudar o período) e **excluir** uma matrícula;
- ver **estatísticas** (consulta agregada: alunos por curso, ativos e período médio);
- ver o **estado do cluster MongoDB** em tempo real (quem é PRIMARY e quem é SECONDARY) e **qual nó atendeu** cada leitura/escrita — útil para demonstrar a distribuição.

## 2. Tecnologias

| Camada | Tecnologia |
|---|---|
| Linguagem | **Python 3.12** + Flask (API/web) + PyMongo (driver) + Gunicorn (servidor) |
| SGBD | **MongoDB 7.0** (NoSQL), em **replica set de 3 containers** (`mongo1`, `mongo2`, `mongo3`) |
| Containers | Docker, **Docker Compose** e **Docker Swarm** |

## 3. Níveis do trabalho atendidos

| Nível | Requisito | Como é atendido |
|---|---|---|
| 1 | App em container + BD em container, via Compose | `docker-compose.yml` (serviço `app` + serviços `mongo*`) |
| 2 | NoSQL distribuído em mais de um container | Replica set `rs0` com 3 containers MongoDB |
| 3 | Swarm com 2 computadores (app em um, SGBD no outro) | `docker-stack.yml` com _placement constraints_ por label (`role=app` / `role=db`) |

## 4. Estrutura do projeto

```
.
├── README.md                 ← este arquivo
├── docker-compose.yml        ← execução em 1 computador (Níveis 1 e 2)
├── docker-stack.yml          ← execução em 2 computadores com Swarm (Nível 3)
├── app/
│   ├── Dockerfile            ← imagem da aplicação
│   ├── requirements.txt
│   ├── app.py                ← código-fonte (comentado)
│   └── templates/index.html  ← interface web
├── mongo/
│   └── init-replica.sh       ← inicializa o replica set (executado por container descartável)
└── slides/
    └── Apresentacao_Docker.pptx
```

## 5. Arquitetura

```
                 ┌──────────────── rede Docker (bridge no Compose / overlay no Swarm) ────────────────┐
 navegador ───►  │  app (Flask/Gunicorn)  ──►  mongo1 (PRIMARY)  ◄──replicação──►  mongo2 (SECONDARY) │
 :8000           │                                     ▲                                  │            │
                 │                                     └───────────replicação──► mongo3 (SECONDARY)    │
                 └─────────────────────────────────────────────────────────────────────────────────────┘
```

- A aplicação conecta ao replica set com `mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0`.
- Escritas usam `w="majority"` (confirmadas por 2 de 3 nós). Leituras usam `primaryPreferred`.
- Se o PRIMARY cair, os dois nós restantes elegem um novo PRIMARY em alguns segundos e a aplicação continua funcionando.
- No Swarm, os containers `app` rodam no **Computador A** e os containers `mongo1..3` no **Computador B**.

---

## 6. Como executar

### 6.1 Pré-requisitos

- **Docker Engine 24+** com o plugin **Docker Compose v2** (`docker compose version`).
- Internet na primeira execução (baixar as imagens `python:3.12-slim` e `mongo:7.0`).
- Porta **8000** livre (ou defina `APP_PORT=8080` para usar outra).

### 6.2 Opção A — Docker Compose (1 computador, Níveis 1 e 2)

```bash
# 1. entre na pasta do projeto
cd alunos-docker

# 2. construa a imagem da aplicação e suba tudo em segundo plano
docker compose up -d --build

# 3. acompanhe: aguarde 'mongo-init' terminar (Exited 0) e 'app' ficar Up
docker compose ps

# 4. acesse no navegador
#    http://localhost:8000
```

Na primeira execução o Compose espera os 3 MongoDB ficarem saudáveis, o `mongo-init` cria o replica set e só então a `app` inicia (~30–60 s).

**Parar / limpar**

```bash
docker compose down        # para e remove os containers (mantém os dados nos volumes)
docker compose down -v     # remove também os volumes (apaga os dados)
```

### 6.3 Opção B — Docker Swarm (2 computadores, Nível 3)

Considere:
- **Computador A** → será o _manager_ e executará a **aplicação**.
- **Computador B** → será o _worker_ e executará o **MongoDB**.
- Os dois precisam estar **na mesma rede** e se enxergar (teste com `ping`). Use IP fixo ou anote os IPs.
- Libere no firewall entre os dois: **2377/tcp**, **7946/tcp+udp** e **4789/udp**. Mais a **8000/tcp** para acessar a aplicação.
- Recomenda-se Linux em ambos (em Docker Desktop para Windows/macOS o Swarm entre máquinas diferentes costuma falhar por causa da VM/NAT).

**Passo 1 — Criar o cluster (no Computador A)**

```bash
docker swarm init --advertise-addr <IP_DO_COMPUTADOR_A>
# o comando imprime um "docker swarm join --token ... <IP_A>:2377": copie-o
```

**Passo 2 — Entrar no cluster (no Computador B)**

```bash
docker swarm join --token <TOKEN_COPIADO> <IP_DO_COMPUTADOR_A>:2377
```

**Passo 3 — Rotular os nós (no Computador A)**

```bash
docker node ls                                   # veja os nomes/IDs dos dois nós
docker node update --label-add role=app <NOME_DO_NO_A>
docker node update --label-add role=db  <NOME_DO_NO_B>
```

**Passo 4 — Preparar as imagens**

```bash
# No Computador A: construir a imagem da aplicação (o Swarm não faz build)
docker build -t alunos-app:1.0 ./app

# No Computador B: baixar a imagem do MongoDB antes (evita depender da internet na hora)
docker pull mongo:7.0
```

**Passo 5 — Implantar a stack (no Computador A, dentro da pasta do projeto)**

```bash
docker stack deploy -c docker-stack.yml --resolve-image never alunos
```

**Passo 6 — Verificar**

```bash
docker stack services alunos       # mongo1..3 = 1/1, app = 2/2, mongo-init = 0/1 (normal: já terminou)
docker stack ps alunos             # coluna NODE: app no nó A, mongo* no nó B
docker service logs alunos_mongo-init
```

Acesse **`http://<IP_DO_COMPUTADOR_A>:8000`** (também funciona pelo IP do B — _routing mesh_ do Swarm).

**Remover**

```bash
docker stack rm alunos
docker swarm leave            # no Computador B
docker swarm leave --force    # no Computador A
```

---

## 7. Testando a aplicação

**Pela interface:** clique em “Carregar exemplos”, matricule um aluno, use a busca, os filtros, o botão Trancar e o Excluir.

**Pela API (substitua `localhost` pelo IP do Computador A no Swarm):**

```bash
# adicionar (matricular)
curl -X POST http://localhost:8000/api/alunos -H "Content-Type: application/json" \
     -d '{"matricula":"20250001","nome":"Maria Silva","curso":"Sistemas de Informação","periodo":5,"email":"maria@exemplo.com"}'

# recuperar (com filtros)
curl "http://localhost:8000/api/alunos"
curl "http://localhost:8000/api/alunos?busca=maria"
curl "http://localhost:8000/api/alunos?curso=Enfermagem&status=Ativo"
curl http://localhost:8000/api/alunos/20250001

# alterar e excluir
curl -X PATCH  http://localhost:8000/api/alunos/20250001 -H "Content-Type: application/json" -d '{"status":"Trancado"}'
curl -X DELETE http://localhost:8000/api/alunos/20250001

# agregação e estado do cluster
curl http://localhost:8000/api/estatisticas
curl http://localhost:8000/api/status
```

**Consultando o MongoDB diretamente:**

```bash
# Compose
docker compose exec mongo1 mongosh escola --eval "db.alunos.find().limit(3)"
# Swarm (no Computador B)
docker exec -it $(docker ps -qf name=alunos_mongo1) mongosh escola --eval "db.alunos.find().limit(3)"
```

### Testando a tolerância a falhas

```bash
# Compose: derrubar o nó que está como PRIMARY
docker compose stop mongo1
# → em ~10 s outro nó vira PRIMARY (veja o painel da aplicação); matricule um aluno: continua funcionando
docker compose start mongo1      # volta como SECONDARY e se ressincroniza
```

No Swarm, ao parar um container do MongoDB (`docker stop <id>` no Computador B) o próprio Swarm o recria automaticamente.

---

## 8. Principais decisões

- **Replica set com 3 nós:** a eleição de PRIMARY exige maioria (2 de 3); com apenas 2 nós, a queda de um impediria a eleição.
- **Sem autenticação no MongoDB** (simplificação acadêmica): as portas do banco **não são publicadas**; só a aplicação, dentro da rede Docker, o acessa. Em produção usaríamos usuário/senha e _keyFile_.
- **`mongo-init`:** container descartável que cria o replica set de forma idempotente.
- **Volumes nomeados** (`mongoN_data`): os dados sobrevivem à recriação dos containers.
- **Healthchecks:** o Compose só inicia a aplicação depois que o banco está pronto; no Swarm o script de inicialização espera os nós por conta própria.
