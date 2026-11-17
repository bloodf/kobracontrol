<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/kobracontrol-hero-dark-pt-BR.png">
    <img alt="Kobra Control: controle a Anycubic Kobra X pelo OrcaSlicer na sua rede" src="assets/readme/kobracontrol-hero-light-pt-BR.png" width="100%">
  </picture>
</p>

<h1 align="center">🟣 Kobra Control</h1>
<p align="center"><b>Controle a Anycubic Kobra X pelo OrcaSlicer na sua rede.</b><br><sub>Um plugin para o OrcaSlicer · by bloodf</sub></p>

<p align="center">
  <a href="https://cloud.orcaslicer.com/p/59c786285255"><img alt="Instalar pelo Orca Cloud" src="https://img.shields.io/badge/Orca_Cloud-Instalar-6240c8?style=for-the-badge"></a>
  <a href="https://github.com/bloodf/kobracontrol/releases/latest"><img alt="Última versão" src="https://img.shields.io/github/v/release/bloodf/kobracontrol?style=for-the-badge&color=6240c8"></a>
  <img alt="OrcaSlicer 2.5+" src="https://img.shields.io/badge/OrcaSlicer-2.5%2B-555?style=for-the-badge">
  <a href="LICENSE"><img alt="Licença" src="https://img.shields.io/github/license/bloodf/kobracontrol?style=for-the-badge&color=555"></a>
</p>

<p align="center">
  <a href="#-instalação">Instalação</a> · <a href="#-recursos">Recursos</a> · <a href="#-como-usar">Como usar</a> · <a href="#-perguntas-frequentes">Perguntas frequentes</a> · <a href="README.md">English</a>
</p>

## ✨ O que faz

O Kobra Control (`kobracontrol`) é um plugin do OrcaSlicer 2.5 para a Anycubic Kobra X. Ele fala direto com a impressora pela rede local e registra um agente de impressora no OrcaSlicer, então os diálogos Print e Send e a aba Device do próprio OrcaSlicer funcionam com a Kobra X. Ele também cria a aba **Kobra Control**, com painel, câmera, os slots de filamento do ACE, os arquivos da impressora e o Spoolman. Não precisa de conta na nuvem nem de pacotes Python extras.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/kobracontrol-dashboard-dark-pt-BR.png">
    <img alt="O Painel durante uma impressão: 37 % concluído, tempo restante, temperaturas do bico e da mesa, a imagem da câmera e os slots de filamento" src="assets/readme/kobracontrol-dashboard-light-pt-BR.png" width="100%">
  </picture>
</p>

## 📦 Instalação

O Kobra Control está no Orca Cloud: abra [a página do plugin](https://cloud.orcaslicer.com/p/59c786285255) e instale por lá.

A partir de um arquivo (os menus do OrcaSlicer aparecem aqui com os nomes em inglês):

1. Baixe `kobracontrol_any.whl` da [última versão](https://github.com/bloodf/kobracontrol/releases/latest).
2. No OrcaSlicer, abra **File > Plugins > Install local plugin** e escolha o arquivo.
3. Marque **Activate** e permita o que o OrcaSlicer pedir. A aba **Kobra Control** aparece ao lado de Prepare, Preview e Device.

| Requisito | Detalhe |
|---|---|
| OrcaSlicer | 2.5.0 ou mais novo, na versão oficial. Não precisa de versão modificada. |
| Impressora | Uma Anycubic Kobra X na mesma rede, com o modo LAN ligado. Conferido no firmware 2.0.2.8. |
| `ffmpeg` | Opcional. A aba Kobra Control mostra a câmera com o player embutido; o `ffmpeg` só é necessário quando esse player não consegue (uma transmissão RTSP, ou um sistema sem suporte a vídeo H.264, possível no Linux). A câmera da aba Device funciona sem ele. |
| Anycubic Slicer Next | Não é necessário. O certificado de cliente que a impressora exige vem no plugin. |
| Spoolman | Opcional, para acompanhar as bobinas. |

> **Situação: em desenvolvimento.** A camada de serviço do plugin foi executada com uma Kobra X real (firmware 2.0.2.8), fora do OrcaSlicer: conexão, status, ACE, arquivos, luz, transmissão da câmera, homing, movimentos, aquecimento e uma impressão a partir de um `.3mf`. Pausar, retomar, parar, alimentar e recolher filamento, secagem, edição de slot, pular objetos, modo de velocidade e o registro de consumo no Spoolman ainda não foram experimentados na impressora, e nada foi testado dentro do próprio OrcaSlicer.

O Kobra Control é um projeto independente. Não é feito nem mantido pela Anycubic.

## 🧰 Recursos

<table>
  <tr>
    <td width="50%" valign="top">
      <img alt="A página Ajustes com a conexão respondendo e o certificado pronto" src="assets/orca-cloud/kobracontrol-feature-01-lan-pt-BR.png" width="100%">
      <p><b>Envie impressões pela rede local</b><br>Print e Send funcionam pelos diálogos do próprio OrcaSlicer. A aba encontra a impressora sozinha e o certificado de cliente já vem no plugin.</p>
    </td>
    <td width="50%" valign="top">
      <img alt="O Painel com progresso, temperaturas e a imagem da câmera" src="assets/orca-cloud/kobracontrol-feature-02-status-pt-BR.png" width="100%">
      <p><b>Acompanhe sua impressão</b><br>Progresso, camada, tempo restante e a hora em que a impressão deve terminar, ao lado de temperaturas, ventoinha, velocidade, luz e câmera.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img alt="Quatro slots do ACE com material, cor, peso restante e secagem a 50 °C" src="assets/orca-cloud/kobracontrol-feature-03-ace-pt-BR.png" width="100%">
      <p><b>Gerencie o filamento de cada slot</b><br>Cada slot da cabeça de impressão e do ACE mostra cor e material, com alimentar, recolher, alimentação automática, secagem e a bobina do Spoolman vinculada.</p>
    </td>
    <td width="50%" valign="top">
      <img alt="A lista de arquivos da impressora e o painel com tempo, camadas, filamento e os slots de cada cor" src="assets/orca-cloud/kobracontrol-feature-04-files-pt-BR.png" width="100%">
      <p><b>Escolha os arquivos antes de imprimir</b><br>Veja os arquivos da impressora e confira tempo, camadas, filamento e qual slot do ACE imprime cada cor antes de pressionar <b>Iniciar impressão</b>.</p>
    </td>
  </tr>
</table>

| Recurso | O que você tem |
|---|---|
| Agente de impressora | O id do agente é `kobracontrol`. Print e Send usam o mapeamento de filamento para slot que você escolhe no diálogo de impressão do OrcaSlicer, com nivelamento automático, calibração de fluxo e time-lapse desse diálogo e a compensação de vibração dos ajustes do plugin. |
| Aba Device | Status, temperaturas, pausar, retomar, parar, luz, ventoinha, velocidade e câmera na aba Device do próprio OrcaSlicer. Os slots do ACE aparecem ali como slots de filamento, com sincronização e mapeamento no diálogo de impressão. |
| Painel | Status e controles, movimentos e homing, a câmera, o cartão de filamento, o painel Impressora e o estoque do Spoolman e do Spooler. |
| Painel Impressora | Nome e **Renomear**, firmware, endereço de rede, contadores de impressão e as chaves do **Assistente de impressão**. |
| Arquivos | Busca e ordenação (mais recentes, mais antigos, nome, tamanho). O painel de impressão avisa quando um slot está com um material diferente do fatiado, quando um filamento não tem slot carregado e quando o arquivo foi fatiado para outra impressora. A confirmação repete o aviso. |
| Time-lapses | Os vídeos de time-lapse da impressora, com impressão, data, duração e tamanho, e **Excluir**. A impressora ainda não oferece um jeito de baixar um vídeo pela rede local. |
| Spoolman | Vincule uma bobina do Spoolman a um slot. As impressões concluídas registram ali o filamento usado quando a opção está ligada. |
| Funciona com o Spooler | O [Spooler](https://github.com/bloodf/spooler) transforma seus filamentos do Spoolman em perfis de filamento do OrcaSlicer. Com ele instalado, o Painel mostra o estoque do Spooler. O Kobra Control também funciona ao lado do [Print Calculator](https://github.com/bloodf/orca_print_calculator). |
| Ajustes | Conexão (com a impressão digital do certificado da impressora), certificado, padrões de impressão, caminho do `ffmpeg`, Spoolman e idioma. Se a impressora apresentar um certificado TLS diferente do anterior, todas as abas mostram um aviso. |
| Plugins > Run | **Check Kobra X connection** informa certificado, credenciais, MQTT e versão do firmware. **Find Anycubic certificate** procura o certificado de cliente e informa o resultado. |

Não há suporte para: Anycubic Cloud e acesso de fora da rede local, console de G-code (o protocolo LAN da impressora não tem) e outros modelos Kobra.

<a id="-como-usar"></a>
## 🛠️ Como usar

1. Ligue o modo LAN na Kobra X e deixe a impressora e o computador na mesma rede.
2. Abra a aba **Kobra Control**. Ela procura a impressora sozinha. Na primeira vez, o OrcaSlicer pergunta uma vez se o kobracontrol pode se conectar àquele endereço. Permita.
3. Use o **Painel** para acompanhar a impressão, definir temperaturas, ligar a câmera com **Ligar** e alimentar, recolher ou secar filamento.
4. Para imprimir um arquivo guardado na impressora, abra **Arquivos**, pressione **Imprimir** no arquivo, confira o painel e pressione **Iniciar impressão**.
5. Para enviar impressões pelo próprio OrcaSlicer, marque **Preferences > Developer > Experimental Features > Use printer agents**. Depois, em uma cópia do seu perfil de impressora da Kobra X, defina **Printer Agent** como `kobracontrol` e o endereço como o IP da impressora.
6. Execute **Plugins > Check Kobra X connection**. Depois, no diálogo de impressão do OrcaSlicer, sincronize os slots do ACE, associe cada filamento a um slot e envie a impressão.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/kobracontrol-files-dark-pt-BR.png">
    <img alt="A aba Arquivos: três arquivos na impressora, quatro vídeos de time-lapse e o painel de impressão de desk_organiser_plate_1.gcode, com o aviso de que o slot 2 está com ABS em vez de PETG" src="assets/readme/kobracontrol-files-light-pt-BR.png" width="100%">
  </picture>
</p>

Os passos 5 e 6 são opcionais. Sem eles a aba funciona sozinha, por exemplo ao lado do Kobralink ou de outra ponte Moonraker que o seu perfil de impressora já usa, e Print, Send e a aba Device do OrcaSlicer continuam usando o agente do próprio perfil.

A aba procura a impressora nesta ordem: o endereço em **Ajustes**, se você definiu um; o endereço que ela encontrou antes para o perfil de impressora selecionado; o endereço do próprio perfil, se uma Kobra X responder ali; e por fim uma busca na rede local (SSDP, do jeito que o Anycubic Slicer Next encontra impressoras).

Depois que a impressão começa, a impressora pode passar muitos minutos em preparação (aquecendo, nivelando e passando pelos slots do ACE) antes da primeira camada. Em um teste isso levou cerca de 11 minutos para uma impressão de 5 minutos. A impressora não travou; enquanto isso o trabalho aparece como imprimindo.

O passo a passo completo e uma tabela de solução de problemas estão em [docs/setup.md](docs/setup.md) (em inglês).

## 🔒 Privacidade e segurança

O Kobra Control se conecta só à Kobra X e ao seu servidor Spoolman, se você configurar um. A impressora é acessada por HTTP na porta 18910 e por MQTT com TLS mútuo na porta 9883, no endereço que você definiu ou em um que o plugin encontrou na rede local e confirmou ser uma Kobra X em modo LAN. A busca na rede envia consultas SSDP apenas para o grupo multicast local 239.255.255.250. Não existe serviço na nuvem.

Use em uma rede em que você confia. A impressora entrega as credenciais MQTT a qualquer um na rede, e o certificado TLS dela é autoassinado e não é verificado, então a conexão só protege contra leitura passiva.

A impressora só aceita o certificado de cliente TLS que acompanha o Anycubic Slicer Next. Esse certificado é uma identidade de cliente compartilhada, igual em todas as cópias do Anycubic Slicer Next, e não um segredo de cada usuário; o plugin já vem com ele. Nem a chave desse certificado nem as credenciais MQTT são enviadas à página ou gravadas em logs.

Na aba, parar uma impressão, aquecer, fazer homing, desligar os motores, pular objetos, alimentar ou recolher filamento, iniciar uma secagem, imprimir um arquivo guardado e excluir arquivos sempre pedem confirmação. Os detalhes estão em [SECURITY.md](SECURITY.md) (em inglês).

## ❓ Perguntas frequentes

<details>
<summary>Preciso ter o Anycubic Slicer Next instalado?</summary>

Não. O certificado de cliente vem no plugin, então não há etapa de certificado. Se um firmware futuro deixar de aceitar a cópia incluída, **Procurar certificado** (em **Ajustes**, na opção avançada do certificado) troca essa cópia pela da sua instalação do Anycubic Slicer Next.
</details>

<details>
<summary>A impressão começou, mas nada se mexe por vários minutos. Travou?</summary>

Não. A impressora aquece, nivela e passa pelos slots do ACE antes da primeira camada. Em um teste isso levou cerca de 11 minutos para uma impressão de 5 minutos.
</details>

<details>
<summary>Posso continuar usando o Kobralink ou outra ponte Moonraker?</summary>

Pode. Deixe o seu perfil de impressora como está. A aba Kobra Control encontra a impressora e funciona sozinha, e Print, Send e a aba Device do OrcaSlicer continuam passando pela ponte. Quando o endereço do perfil é de uma ponte e não da impressora, a aba avisa em uma linha.
</details>

<details>
<summary>Por que o OrcaSlicer pede permissão para executar o ffmpeg?</summary>

Só quando o player embutido não consegue mostrar a câmera a aba Kobra Control usa o `ffmpeg` para transformar a transmissão da impressora em imagens. Quando ele inicia, o OrcaSlicer mostra o comando completo, com o endereço da transmissão, e pergunta. Ele pergunta de novo quando esse endereço muda, o que acontece quando a impressora reinicia. A câmera da aba Device não precisa do `ffmpeg`.
</details>

<details>
<summary>Nada conecta, ou aparece "No Kobra X answered the network search".</summary>

Confira se o modo LAN está ligado na impressora e se ela e o computador estão na mesma rede. Se a sua rede bloqueia multicast, digite o IP da impressora em **Ajustes > Endereço da impressora**.
</details>

<details>
<summary>"Something answers at … but it is not a Kobra X in LAN mode".</summary>

O endereço é de outro aparelho, muitas vezes uma ponte como o Kobralink, ou o modo LAN está desligado. Deixe **Ajustes > Endereço da impressora** em branco para a aba procurar, ou digite ali o IP da própria impressora.
</details>

<details>
<summary>O perfil de impressora não tem o Printer Agent kobracontrol.</summary>

**Use printer agents** está desligado. Ligue em **Preferences > Developer > Experimental Features** e reinicie o OrcaSlicer.
</details>

<details>
<summary>Dá para baixar os vídeos de time-lapse?</summary>

Ainda não. Não se conhece um jeito de a impressora entregar um vídeo pela rede local, então a aba só lista e exclui.
</details>

## 🌍 Idiomas

Inglês, português do Brasil, espanhol, alemão e chinês simplificado. A aba segue o idioma do OrcaSlicer, e **Ajustes > Idioma** muda isso.

## 🧩 Mais plugins do bloodf

| | Plugin | O que faz | |
|:-:|---|---|---|
| <img src="https://raw.githubusercontent.com/bloodf/orca_organizer/main/assets/orca-cloud/orca_organizer-tile.png" alt="Ícone do Organizer" width="40"> | 🧩 [Organizer](https://github.com/bloodf/orca_organizer) | Organize as peças pelo contorno real e encha a mesa com mais cópias. | [Instalar](https://cloud.orcaslicer.com/p/5bf381fd42d4) |
| <img src="https://raw.githubusercontent.com/bloodf/embedder/main/assets/orca-cloud/embedder-tile.png" alt="Ícone do Embedder" width="40"> | 🧲 [Embedder](https://github.com/bloodf/embedder) | Bolsos para ímãs e NFC, com a pausa na camada certa. | [Instalar](https://cloud.orcaslicer.com/p/58222d4f9e52) |
| <img src="https://raw.githubusercontent.com/bloodf/orca_print_calculator/main/assets/orca-cloud/orca_print_calculator-tile.png" alt="Ícone do Print Calculator" width="40"> | 💰 [Print Calculator](https://github.com/bloodf/orca_print_calculator) | Preço de cada mesa: filamento, energia, mão de obra, taxas e margem. | [Instalar](https://cloud.orcaslicer.com/p/521c07cf6de2) |
| <img src="https://raw.githubusercontent.com/bloodf/spooler/main/assets/orca-cloud/spooler-tile.png" alt="Ícone do Spooler" width="40"> | 🧵 [Spooler](https://github.com/bloodf/spooler) | Seu estoque do Spoolman dentro do OrcaSlicer, com o que resta em cada bobina. | [Instalar](https://cloud.orcaslicer.com/p/50c35dcbd6f3) |
| <img src="assets/orca-cloud/kobracontrol-tile.png" alt="Ícone do Kobra Control" width="40"> | 🟣 **Kobra Control** · você está aqui | Controle a Anycubic Kobra X pelo OrcaSlicer na sua rede. | |
| <img src="https://raw.githubusercontent.com/bloodf/u1control/main/assets/orca-cloud/u1control-tile.png" alt="Ícone do U1 Control" width="40"> | 🔵 [U1 Control](https://github.com/bloodf/u1control) | Controle a Snapmaker U1 pelo OrcaSlicer: cabeças, câmera, arquivos. | [Instalar](https://cloud.orcaslicer.com/p/55b8c347d443) |

Cada plugin funciona sozinho; instalados juntos, compartilham dados onde ajuda.

## 🤝 Contribuir

Relatos de problemas, logs e pull requests são bem-vindos. Comece pelo [CONTRIBUTING.md](CONTRIBUTING.md). A documentação para desenvolvedores fica em [docs/](docs/) e está em inglês: [configuração](docs/setup.md), [arquitetura](docs/architecture.md), [protocolo](docs/protocol.md), [publicação](docs/release.md) e a [descrição do Orca Cloud](docs/orca-cloud-description.md). Veja também o [histórico de mudanças](CHANGELOG.md), as [notas de segurança](SECURITY.md) e o [NOTICE.md](NOTICE.md), com os créditos dos projetos de onde o código do protocolo foi portado.

## 📄 Licença

GPL-3.0-only. Veja o [LICENSE](LICENSE).

<p align="center"><sub>by bloodf</sub></p>
