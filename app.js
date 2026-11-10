const $ = (selector) => document.querySelector(selector);
const DAY = 86400000;
const today = new Date(); today.setHours(0,0,0,0);
let selectedDate = new Date(today);
const palettes = ['blue','green','orange'];
const categories = [
  {name:'PRONOS 1',tag:'SÉLECTION 01',description:'Une première sélection de rencontres.',matches:[['Lions FC','United Stars','Ligue de démonstration','Victoire domicile','1.55'],['Riverside','Olympique Nord','Coupe de démonstration','Plus de 1,5 buts','1.42']]},
  {name:'PRONOS 2',tag:'SÉLECTION 02',description:'Une deuxième sélection de rencontres.',matches:[['Atlantic SC','Mountain FC','Championnat de démonstration','Les deux équipes marquent','1.70'],['City Athletic','Royal Blue','Ligue de démonstration','Double chance 1X','1.38']]},
  {name:'PRONOS 3',tag:'SÉLECTION 03',description:'Une troisième sélection de rencontres.',matches:[['Green Valley','Capital FC','Coupe de démonstration','Moins de 3,5 buts','1.48'],['Sporting East','West Rangers','Championnat de démonstration','Plus de 2,5 buts','1.85']]}
];
const dateFmt = new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
const shortFmt = new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'});
function dateKey(date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`}
function dayOffset(){return Math.round((selectedDate-today)/DAY)}
function updateDate(){
  const offset=dayOffset();
  $('#dateLabel').textContent=dateFmt.format(selectedDate);
  $('#dateHint').textContent=offset===0?'Pronostics et résultats du jour':offset<0?`Archives — il y a ${Math.abs(offset)} jour${Math.abs(offset)>1?'s':''}`:`Prévisions — dans ${offset} jour${offset>1?'s':''}`;
  $('#prevBtn').disabled=offset<=-10; $('#nextBtn').disabled=offset>=2;
  $('#rangeProgress').style.width=`${((offset+10)/12)*100}%`;
  renderCards();
}
function renderCards(){
  $('#selectionGrid').innerHTML=categories.map((item,i)=>`<button class="selection-card" data-category="${i}" aria-label="Ouvrir ${item.name}"><span class="card-banner ${palettes[i]}" data-number="0${i+1}"><strong>${item.name}</strong></span><span class="card-body"><span class="card-kicker">${item.tag}</span><p>${item.description}</p><span class="card-bottom">Consulter la sélection <span class="card-arrow">→</span></span></span></button>`).join('');
  document.querySelectorAll('[data-category]').forEach(card=>card.addEventListener('click',()=>openCategory(Number(card.dataset.category))));
}
function openCategory(index){
  const item=categories[index]; $('#dialogEyebrow').textContent=item.tag; $('#dialogTitle').textContent=item.name; $('#dialogDate').textContent=dateFmt.format(selectedDate);
  $('#matchList').innerHTML=item.matches.map((m,i)=>`<article class="match-card"><div class="match-meta"><span>${m[2]}</span><span>${i===0?'16:00':'19:30'}</span></div><div class="match-teams"><span>${m[0]}</span><span>VS</span><span>${m[1]}</span></div><div class="match-pick"><span>Pronostic de démonstration : <strong>${m[3]}</strong></span><strong>Cote ${m[4]}</strong></div></article>`).join('');
  $('#contentDialog').showModal();
}
$('#prevBtn').addEventListener('click',()=>{if(dayOffset()>-10){selectedDate=new Date(selectedDate.getTime()-DAY);updateDate()}});
$('#nextBtn').addEventListener('click',()=>{if(dayOffset()<2){selectedDate=new Date(selectedDate.getTime()+DAY);updateDate()}});
$('#todayBtn').addEventListener('click',()=>{selectedDate=new Date(today);updateDate()});
$('#closeDialog').addEventListener('click',()=>$('#contentDialog').close());
$('#contentDialog').addEventListener('click',e=>{if(e.target===$('#contentDialog'))$('#contentDialog').close()});
const info={privacy:['Politique de confidentialité','Cette page sera complétée avant la mise en production pour expliquer quelles données sont collectées, pourquoi elles le sont et comment exercer vos droits.'],legal:['Mentions légales','Les coordonnées de l’éditeur et de l’hébergeur seront ajoutées avant la publication officielle.'],terms:['Conditions d’utilisation','Les conditions d’utilisation seront publiées avant l’ouverture publique de Goal4win.']};
[['privacyLink','privacy'],['legalLink','legal'],['termsLink','terms']].forEach(([id,key])=>{$('#'+id).addEventListener('click',e=>{e.preventDefault();$('#infoTitle').textContent=info[key][0];$('#infoText').textContent=info[key][1];$('#infoDialog').showModal()})});
$('#closeInfo').addEventListener('click',()=>$('#infoDialog').close());
$('#year').textContent=new Date().getFullYear();
updateDate();
if('serviceWorker' in navigator && location.protocol.startsWith('http')) window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(err=>console.info('Service worker non enregistré',err)));
