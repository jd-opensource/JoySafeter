use std::time::Duration;

use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_client::AggregatedDiscoveryServiceClient,
    aggregated_discovery_service_server::AggregatedDiscoveryServiceServer,
};
use joysafeter_orchestrator::xds::authority::{AuthorityPhase, XdsAuthority};
use joysafeter_orchestrator::xds::delta::DeltaXdsServer;
use joysafeter_orchestrator::xds::node_ownership::NodeOwnershipRegistry;
use joysafeter_orchestrator::xds::resource_store::XdsResourceStore;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tonic::transport::Server;

#[test]
fn mutations_are_admitted_only_after_recovery_is_ready() {
    let authority = XdsAuthority::managed();

    assert_eq!(authority.phase(), AuthorityPhase::Standby);
    assert!(authority.recovery_guard().is_none());
    assert!(authority.mutation_guard().is_none());

    let recovery = authority.begin_staging().expect("begin staging");
    assert_eq!(authority.phase(), AuthorityPhase::Staging { epoch: 1 });
    assert_eq!(recovery.epoch(), 1);
    recovery.validate().expect("staging recovery guard");
    assert!(authority.mutation_guard().is_none());

    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    assert_eq!(
        authority.phase(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );
    recovery.validate().expect("recovery-serving guard");
    assert!(authority.mutation_guard().is_none());

    authority.mark_ready(&recovery).expect("mark ready");
    assert_eq!(authority.phase(), AuthorityPhase::Ready { epoch: 1 });
    assert!(recovery.validate().is_err());
    authority
        .mutation_guard()
        .expect("ready mutation guard")
        .validate()
        .expect("current mutation guard");
}

#[test]
fn delivery_epoch_must_match_the_current_serving_authority() {
    let authority = XdsAuthority::managed();
    let first = authority.begin_staging().expect("begin first staging");
    assert!(authority.validate_delivery_epoch(first.epoch()).is_err());
    authority
        .begin_recovery_serving(&first)
        .expect("begin first recovery serving");
    authority
        .validate_delivery_epoch(first.epoch())
        .expect("recovery-serving epoch");
    authority.mark_ready(&first).expect("mark first ready");
    authority
        .validate_delivery_epoch(first.epoch())
        .expect("ready epoch");

    authority.revoke().expect("revoke first epoch");
    assert!(authority.validate_delivery_epoch(first.epoch()).is_err());
    let second = authority.begin_staging().expect("begin second staging");
    authority
        .begin_recovery_serving(&second)
        .expect("begin second recovery serving");
    assert!(authority.validate_delivery_epoch(first.epoch()).is_err());
    authority
        .validate_delivery_epoch(second.epoch())
        .expect("current epoch");
}

#[test]
fn revocation_and_new_epoch_invalidate_old_guards() {
    let authority = XdsAuthority::managed();
    let first_recovery = authority.begin_staging().expect("first staging");
    authority
        .begin_recovery_serving(&first_recovery)
        .expect("first recovery serving");
    authority.mark_ready(&first_recovery).expect("first ready");
    let first_mutation = authority.mutation_guard().expect("first mutation guard");

    authority.revoke().expect("revoke first epoch");
    assert_eq!(authority.phase(), AuthorityPhase::Revoked { epoch: 1 });
    assert!(first_recovery.validate().is_err());
    assert!(first_mutation.validate().is_err());

    let second_recovery = authority.begin_staging().expect("second staging");
    assert_eq!(second_recovery.epoch(), 2);
    assert_eq!(authority.phase(), AuthorityPhase::Staging { epoch: 2 });
    assert!(first_mutation.validate().is_err());
    second_recovery.validate().expect("second recovery guard");
}

#[test]
fn guards_cannot_be_reused_across_authority_instances() {
    let first = XdsAuthority::managed();
    let second = XdsAuthority::managed();
    let foreign_guard = first.begin_staging().expect("first staging");
    let local_guard = second.begin_staging().expect("second staging");

    assert!(second.begin_recovery_serving(&foreign_guard).is_err());
    assert_eq!(second.phase(), AuthorityPhase::Staging { epoch: 1 });
    second
        .begin_recovery_serving(&local_guard)
        .expect("local guard remains valid");
}

#[tokio::test]
async fn phase_watcher_observes_each_authority_transition() {
    let authority = XdsAuthority::standalone();
    let mut phases = authority.subscribe();

    let recovery = authority.begin_staging().expect("begin staging");
    phases.changed().await.expect("staging transition");
    assert_eq!(
        *phases.borrow_and_update(),
        AuthorityPhase::Staging { epoch: 1 }
    );

    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    phases.changed().await.expect("recovery-serving transition");
    assert_eq!(
        *phases.borrow_and_update(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );

    authority.mark_ready(&recovery).expect("mark ready");
    phases.changed().await.expect("ready transition");
    assert_eq!(
        *phases.borrow_and_update(),
        AuthorityPhase::Ready { epoch: 1 }
    );

    authority.revoke().expect("revoke");
    phases.changed().await.expect("revoked transition");
    assert_eq!(
        *phases.borrow_and_update(),
        AuthorityPhase::Revoked { epoch: 1 }
    );
}

#[tokio::test]
async fn ads_admission_tracks_recovery_serving_and_revocation() {
    let authority = XdsAuthority::managed();
    let server = DeltaXdsServer::new(
        authority.clone(),
        XdsResourceStore::new(),
        NodeOwnershipRegistry::unscoped(),
    );
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind xDS test listener");
    let address = listener.local_addr().expect("read xDS test address");
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let service = server.clone();
    let server_task = tokio::spawn(async move {
        Server::builder()
            .add_service(AggregatedDiscoveryServiceServer::from_arc(service))
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                let _ = shutdown_rx.await;
            })
            .await
    });

    let channel = tonic::transport::Endpoint::from_shared(format!("http://{address}"))
        .expect("build xDS test endpoint")
        .connect()
        .await
        .expect("connect xDS test client");
    let mut client = AggregatedDiscoveryServiceClient::new(channel);

    assert_ads_rejected(&mut client).await;
    let recovery = authority.begin_staging().expect("begin staging");
    assert_ads_rejected(&mut client).await;

    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    let (_active_tx, active_rx) = tokio::sync::mpsc::channel(1);
    let mut stream = client
        .delta_aggregated_resources(ReceiverStream::new(active_rx))
        .await
        .expect("recovery-serving authority must admit ADS")
        .into_inner();

    authority.mark_ready(&recovery).expect("mark ready");
    let (_ready_tx, ready_rx) = tokio::sync::mpsc::channel(1);
    client
        .delta_aggregated_resources(ReceiverStream::new(ready_rx))
        .await
        .expect("ready authority must admit ADS");

    authority.revoke().expect("revoke");
    let closed = tokio::time::timeout(Duration::from_secs(1), stream.message())
        .await
        .expect("revoked ADS stream must close promptly")
        .expect("revoked ADS stream must close without transport error");
    assert!(closed.is_none());
    assert_ads_rejected(&mut client).await;

    let _ = shutdown_tx.send(());
    server_task
        .await
        .expect("join xDS test server")
        .expect("stop xDS test server");
}

async fn assert_ads_rejected(
    client: &mut AggregatedDiscoveryServiceClient<tonic::transport::Channel>,
) {
    let (_tx, rx) = tokio::sync::mpsc::channel(1);
    let error = client
        .delta_aggregated_resources(ReceiverStream::new(rx))
        .await
        .expect_err("non-serving authority must reject ADS");
    assert_eq!(error.code(), tonic::Code::Unavailable);
}
